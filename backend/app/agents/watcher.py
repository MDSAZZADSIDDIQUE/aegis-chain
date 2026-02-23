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


async def run_watcher_cycle() -> dict[str, Any]:
    """Execute a full Watcher analysis cycle.

    1. Run TS predictive bucketing on latency logs.
    2. Fetch active weather threat polygons.
    3. Run ST_INTERSECTS to find ERP locations within threat zones.
    4. Aggregate total $ value_at_risk.
    """
    es = get_es_client()
    results: dict[str, Any] = {
        "bottleneck_predictions": [],
        "at_risk_locations": [],
        "total_value_at_risk": 0.0,
        "threat_correlations": [],
    }

    # Step 1: Predictive bucketing — identify suppliers with rising delays
    try:
        ts_result = es.esql.query(query=WATCHER_ESQL_RISK_ASSESSMENT, format="json")
        columns = [c["name"] for c in ts_result.get("columns", [])]
        rows = ts_result.get("values", [])
        predictions = [dict(zip(columns, row)) for row in rows]
        results["bottleneck_predictions"] = predictions
        logger.info("Watcher found %d bottleneck predictions", len(predictions))
    except Exception as exc:
        logger.error("Watcher TS query failed: %s", exc)

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
    logger.info(
        "Watcher cycle complete: %d threats, %d locations at risk, $%.2f VAR",
        len(results["threat_correlations"]),
        len(results["at_risk_locations"]),
        total_var,
    )

    return results
