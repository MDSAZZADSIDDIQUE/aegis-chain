"""Agent 1 — Watcher Agent.

Performs time-series predictive bucketing using ES|QL TS command and
correlates predicted bottlenecks with active weather threats via
ST_INTERSECTS. Outputs a ranked list of locations with $ value at risk.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.elastic import get_es_client

logger = logging.getLogger("aegis.agent.watcher")

# ES|QL query: predictive bucketing over supply-latency-logs
# + intersection with active weather threats
WATCHER_ESQL_RISK_ASSESSMENT = """FROM supply-latency-logs
| WHERE @timestamp >= NOW() - 72 HOURS
| STATS
    avg_delay     = AVG(delay_hours),
    max_delay     = MAX(delay_hours),
    shipment_count = COUNT(*),
    total_value    = SUM(shipment_value_usd)
  BY location_id, supplier_id
| WHERE avg_delay > 2.0
| SORT avg_delay DESC
| LIMIT 50"""

WATCHER_ESQL_GEO_INTERSECT = """FROM erp-locations
| WHERE active == true
| EVAL at_risk = ST_INTERSECTS(coordinates, TO_GEOSHAPE(?::geo_shape))
| WHERE at_risk == true
| KEEP location_id, name, type, coordinates, inventory_value_usd, reliability_index
| SORT inventory_value_usd DESC"""


def _composite_risk(delay_hours: float, ml_score: float | None) -> float:
    """Blend delay signal and ML anomaly score into a [0, 1] composite.

    Weights
    -------
    ML available   : 0.55 × delay_signal + 0.45 × ml_signal
    ML unavailable : 0.75 × delay_signal  (penalty for missing corroboration)

    Delay signal is normalised against a 24-hour ceiling.
    """
    delay_signal = min(delay_hours / 24.0, 1.0)
    if ml_score is not None:
        return round(0.55 * delay_signal + 0.45 * (ml_score / 100.0), 4)
    return round(0.75 * delay_signal, 4)


async def run_watcher_cycle() -> dict[str, Any]:
    """Execute a full Watcher analysis cycle.

    1.   ES|QL predictive bucketing on supply-latency-logs.
    1.5. Query aegis-ml-results for anomaly_score ≥ 75 (last 72 h).
         Merge both signals → composite_risk_score per (location, supplier).
    2.   Fetch active weather threat polygons.
    3.   ST_INTERSECTS to find ERP locations inside threat zones.
    4.   Aggregate total $ value_at_risk.
    5.   Enrich threat_correlations with ML corroboration flags.
    """
    es = get_es_client()
    results: dict[str, Any] = {
        "bottleneck_predictions": [],
        "ml_anomalies": [],
        "at_risk_locations": [],
        "total_value_at_risk": 0.0,
        "threat_correlations": [],
    }

    # ── Step 1: Predictive bucketing ─────────────────────────────────────────
    try:
        ts_result = es.esql.query(query=WATCHER_ESQL_RISK_ASSESSMENT)
        columns = [col.name for col in ts_result.columns]
        predictions = [dict(zip(columns, row)) for row in ts_result.values]
        results["bottleneck_predictions"] = predictions
        logger.info("Watcher found %d bottleneck predictions", len(predictions))
    except Exception as exc:
        logger.error("Watcher TS query failed: %s", exc)
        predictions = []

    # ── Step 1.5: ML anomaly signals ─────────────────────────────────────────
    # Query aegis-ml-results for any record-level anomaly with score ≥ 75 in
    # the last 72 hours.  Keep the highest-scoring record per entity so that
    # one noisy burst doesn't double-count.
    ml_by_entity: dict[str, dict[str, Any]] = {}
    try:
        ml_resp = es.search(
            index="aegis-ml-results",
            body={
                "size": 200,
                "query": {
                    "bool": {
                        "filter": [
                            {"range": {"timestamp": {"gte": "now-72h"}}},
                            {
                                "bool": {
                                    "should": [
                                        {"range": {"anomaly_score": {"gte": 75}}},
                                        {"range": {"record_score": {"gte": 75}}},
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                            {"term": {"result_type": "record"}},
                        ]
                    }
                },
                "sort": [{"anomaly_score": "desc"}, {"record_score": "desc"}],
                "_source": [
                    "timestamp", "anomaly_score", "record_score",
                    "supplier_id", "location_id",
                    "by_field_value", "over_field_value",
                    "job_id", "function", "actual", "typical",
                ],
            },
        )
        for hit in ml_resp["hits"]["hits"]:
            src = hit["_source"]
            # Resolve entity key — prefer explicit FK fields, then ML by/over fields
            entity_id = (
                src.get("supplier_id")
                or src.get("location_id")
                or src.get("by_field_value")
                or src.get("over_field_value")
            )
            if not entity_id:
                continue
            score = max(
                src.get("anomaly_score") or 0,
                src.get("record_score") or 0,
            )
            existing = ml_by_entity.get(entity_id)
            if not existing or score > max(
                existing.get("anomaly_score") or 0,
                existing.get("record_score") or 0,
            ):
                ml_by_entity[entity_id] = src

        results["ml_anomalies"] = list(ml_by_entity.values())
        logger.info(
            "ML signal: %d anomaly record(s) ≥ 75 in last 72 h", len(ml_by_entity)
        )
    except Exception as exc:
        logger.warning(
            "aegis-ml-results query failed (index not yet populated): %s", exc
        )

    # Enrich each bottleneck prediction with composite_risk_score
    for pred in results["bottleneck_predictions"]:
        supplier_id = pred.get("supplier_id")
        location_id = pred.get("location_id")
        avg_delay   = pred.get("avg_delay", 0) or 0

        ml_record = ml_by_entity.get(supplier_id) or ml_by_entity.get(location_id)
        ml_score  = None
        if ml_record:
            ml_score = max(
                ml_record.get("anomaly_score") or 0,
                ml_record.get("record_score") or 0,
            ) or None

        pred["composite_risk_score"] = _composite_risk(avg_delay, ml_score)
        pred["ml_anomaly_score"] = ml_score
        pred["ml_function"]      = ml_record.get("function") if ml_record else None
        pred["ml_job_id"]        = ml_record.get("job_id") if ml_record else None

    # Re-sort predictions by composite_risk_score descending
    results["bottleneck_predictions"].sort(
        key=lambda p: p.get("composite_risk_score", 0), reverse=True
    )

    # Step 2: Fetch active threat polygons
    try:
        threats_resp = es.search(
            index="weather-threats",
            body={
                "size": 100,
                "query": {"term": {"status": "active"}},
                "_source": ["threat_id", "event_type", "severity", "affected_zone", "headline"],
            },
        )
        threats = [h["_source"] for h in threats_resp["hits"]["hits"]]
    except Exception as exc:
        logger.error("Failed to fetch active threats: %s", exc)
        threats = []

    # Step 3: For each threat, find intersecting ERP locations
    total_var = 0.0
    for threat in threats:
        zone = threat.get("affected_zone")
        if not zone:
            continue

        try:
            # Use geo_shape query to find locations within the threat zone
            geo_resp = es.search(
                index="erp-locations",
                body={
                    "size": 100,
                    "query": {
                        "bool": {
                            "filter": [
                                {"geo_shape": {
                                    "coordinates": {
                                        "shape": zone,
                                        "relation": "intersects",
                                    }
                                }},
                                {"term": {"active": True}},
                            ]
                        }
                    },
                    "aggs": {
                        "value_at_risk": {"sum": {"field": "inventory_value_usd"}}
                    },
                },
            )

            at_risk_locs = [h["_source"] for h in geo_resp["hits"]["hits"]]
            zone_var = (
                geo_resp.get("aggregations", {})
                .get("value_at_risk", {})
                .get("value", 0)
            )
            total_var += zone_var

            if at_risk_locs:
                results["threat_correlations"].append({
                    "threat_id": threat["threat_id"],
                    "event_type": threat["event_type"],
                    "severity": threat["severity"],
                    "headline": threat.get("headline", ""),
                    "affected_locations": [
                        {
                            "location_id": loc["location_id"],
                            "name": loc["name"],
                            "type": loc["type"],
                            "inventory_value_usd": loc.get("inventory_value_usd", 0),
                        }
                        for loc in at_risk_locs
                    ],
                    "zone_value_at_risk": zone_var,
                })

                results["at_risk_locations"].extend(at_risk_locs)

        except Exception as exc:
            logger.error("Geo intersect failed for threat %s: %s", threat["threat_id"], exc)

    results["total_value_at_risk"] = total_var

    # ── Step 5: Enrich threat_correlations with ML corroboration ─────────────
    # Build a fast lookup from location_id → best composite_risk_score.
    risk_by_location: dict[str, float] = {}
    ml_flag_by_location: dict[str, bool] = {}
    for pred in results["bottleneck_predictions"]:
        loc = pred.get("location_id")
        if loc:
            score = pred.get("composite_risk_score", 0)
            if score > risk_by_location.get(loc, 0):
                risk_by_location[loc] = score
                ml_flag_by_location[loc] = pred.get("ml_anomaly_score") is not None

    for corr in results["threat_correlations"]:
        composite_scores = [
            risk_by_location[loc["location_id"]]
            for loc in corr["affected_locations"]
            if loc["location_id"] in risk_by_location
        ]
        corr["max_composite_risk"] = round(max(composite_scores), 4) if composite_scores else 0.0
        corr["ml_corroborated"] = any(
            ml_flag_by_location.get(loc["location_id"], False)
            for loc in corr["affected_locations"]
        )

    logger.info(
        "Watcher cycle complete: %d threats, %d locations at risk, $%.2f VAR, "
        "%d ML anomalies, %d ML-corroborated correlations",
        len(results["threat_correlations"]),
        len(results["at_risk_locations"]),
        total_var,
        len(results["ml_anomalies"]),
        sum(1 for c in results["threat_correlations"] if c.get("ml_corroborated")),
    )

    return results
