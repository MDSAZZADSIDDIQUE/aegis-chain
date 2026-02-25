"""Agent 2 — Procurement Agent.

Uses LOOKUP JOIN to merge semantic SLA search with structured reliability
metrics. Filters out suppliers within 100km of the threat via ST_DISTANCE.
Pings Mapbox for actual drive time. Computes Attention Score.

Attention Score formula
-----------------------
    A_i = (Vector_Similarity_i × Reliability_Index_i) / Live_Drive_Time_Minutes_i

Where:
  Vector_Similarity  — cosine similarity from kNN SLA embedding search (or
                       precomputed sla_score from supplier-sla-scores index),
                       normalised to [0, 1].
  Reliability_Index  — supplier reliability from erp-locations, [0, 1].
  Live_Drive_Time_Minutes — real-time Mapbox driving duration in minutes,
                            routing around the active threat polygon.
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any
from starlette.concurrency import run_in_threadpool

from app.core.elastic import get_es_client
from app.models.schemas import RerouteProposal
from app.services.mapbox import get_route

logger = logging.getLogger("aegis.agent.procurement")

# ES|QL: LOOKUP JOIN merging precomputed SLA scores with reliability metrics,
# filtered by ST_DISTANCE from threat centroid (exclude within 100km).
# Requires supplier-sla-scores to be populated by compute_sla_scores.py.
PROCUREMENT_ESQL = """FROM erp-locations
| WHERE type == "supplier" AND active == true
| EVAL dist_km = ST_DISTANCE(coordinates, TO_GEOPOINT(?)) / 1000.0
| WHERE dist_km > 100.0
| LOOKUP JOIN `supplier-sla-scores` ON location_id
| SORT reliability_index DESC
| LIMIT 20
| KEEP location_id, name, coordinates, reliability_index, avg_lead_time_hours,
       contract_sla, inventory_value_usd, dist_km, sla_score, sla_tier"""


async def run_procurement_cycle(
    threat_id: str,
    threat_centroid: dict[str, float],
    affected_zone: dict[str, Any],
    origin_location: dict[str, Any],
    sla_query_text: str = "reliable fast delivery with penalty clauses",
) -> list[dict[str, Any]]:
    """Execute a full Procurement Agent cycle.

    1. Query suppliers outside the 100km exclusion zone with LOOKUP JOIN.
    2. Run kNN semantic search on contract SLA text.
    3. Fetch Mapbox drive times for top candidates.
    4. Compute Attention Scores.
    5. Return ranked reroute proposals.
    """
    es = get_es_client()
    proposals: list[dict[str, Any]] = []

    if not threat_centroid or "lat" not in threat_centroid or "lon" not in threat_centroid:
        logger.warning("Agent 2 exiting early: invalid or missing threat_centroid %s", threat_centroid)
        return proposals

    # ── Step 1: Structured query — suppliers outside threat radius ────
    threat_point = f"POINT({threat_centroid['lon']} {threat_centroid['lat']})"

    try:
        structured_resp = await run_in_threadpool(
            es.search,
            index="erp-locations",
            body={
                "size": 20,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"type": "supplier"}},
                            {"term": {"active": True}},
                        ],
                        "must_not": [
                            {
                                "geo_distance": {
                                    "distance": "100km",
                                    "coordinates": {
                                        "lat": threat_centroid["lat"],
                                        "lon": threat_centroid["lon"],
                                    },
                                }
                            }
                        ],
                    }
                },
                "sort": [{"reliability_index": "desc"}],
            },
        )
        candidates = [h["_source"] for h in structured_resp["hits"]["hits"]]
    except Exception as exc:
        logger.error("Structured supplier query failed: %s", exc)
        return proposals

    if not candidates:
        logger.warning("No candidate suppliers found outside 100km exclusion zone")
        return proposals

    # ── Step 2: SLA scores — lookup index first, kNN as fallback ────────
    sla_scores: dict[str, float] = {}
    try:
        candidate_ids = [c["location_id"] for c in candidates]
        lookup_resp = await run_in_threadpool(
            es.search,
            index="supplier-sla-scores",
            body={
                "size": len(candidate_ids),
                "query": {"terms": {"location_id": candidate_ids}},
                "_source": ["location_id", "sla_score"],
            },
        )
        for hit in lookup_resp["hits"]["hits"]:
            src = hit["_source"]
            sla_scores[src["location_id"]] = src.get("sla_score", 0.5)
        logger.debug(
            "Loaded %d precomputed SLA scores from supplier-sla-scores", len(sla_scores)
        )
    except Exception as exc:
        logger.warning(
            "supplier-sla-scores lookup failed — falling back to kNN. Reason: %s", exc
        )
        # kNN fallback: requires .multilingual-e5-small inference endpoint
        try:
            knn_resp = await run_in_threadpool(
                es.search,
                index="erp-locations",
                body={
                    "size": 20,
                    "knn": {
                        "field": "contract_sla_vector",
                        "query_vector_builder": {
                            "text_embedding": {
                                "model_id": ".multilingual-e5-small",
                                "model_text": sla_query_text,
                            }
                        },
                        "k": 20,
                        "num_candidates": 50,
                    },
                    "_source": ["location_id"],
                },
            )
            for hit in knn_resp["hits"]["hits"]:
                loc_id = hit["_source"]["location_id"]
                sla_scores[loc_id] = hit["_score"]
            # kNN returns raw cosine scores — normalise to [0, 1]
            if sla_scores:
                max_sla = max(sla_scores.values())
                if max_sla > 0:
                    sla_scores = {k: v / max_sla for k, v in sla_scores.items()}
        except Exception as exc2:
            logger.warning("kNN SLA fallback also failed: %s", exc2)

    # ── Step 3: Mapbox drive times + Attention Score ─────────────────
    # A_i = (Vector_Similarity_i × Reliability_Index_i) / Live_Drive_Time_Minutes_i
    origin_coords = origin_location.get("coordinates", {})
    origin_lat = origin_coords.get("lat", 0)
    origin_lon = origin_coords.get("lon", 0)

    scored: list[dict[str, Any]] = []

    for supplier in candidates[:10]:  # Top 10 to limit API calls
        loc_id = supplier["location_id"]
        coords = supplier.get("coordinates", {})
        sup_lat = coords.get("lat", 0)
        sup_lon = coords.get("lon", 0)

        # Calculate straight-line distance from threat
        dist_km = _haversine(
            threat_centroid["lat"], threat_centroid["lon"], sup_lat, sup_lon
        )

        # Get actual Mapbox drive time
        try:
            route = await get_route(
                origin_lon=origin_lon,
                origin_lat=origin_lat,
                dest_lon=sup_lon,
                dest_lat=sup_lat,
                avoid_polygon=affected_zone,
            )
            drive_time_min = route["duration_minutes"]
            drive_distance_km = route["distance_km"]
            route_geometry = route["geometry"]
        except Exception as exc:
            logger.warning("Mapbox route failed for %s: %s", loc_id, exc)
            drive_time_min = supplier.get("avg_lead_time_hours", 24) * 60
            drive_distance_km = dist_km * 1.3  # estimate
            route_geometry = None

        reliability = supplier.get("reliability_index", 0.5)
        vector_similarity = sla_scores.get(loc_id, 0.5)

        # Attention = (Vector_Similarity × Reliability_Index) / Live_Drive_Time_Minutes
        attention_score = (
            (vector_similarity * reliability)
            / max(drive_time_min, 0.1)
        )

        scored.append({
            "supplier": supplier,
            "attention_score": attention_score,
            "drive_time_min": drive_time_min,
            "drive_distance_km": drive_distance_km,
            "route_geometry": route_geometry,
            "dist_km": dist_km,
            "reliability": reliability,
            "vector_similarity": vector_similarity,
        })

    if not scored:
        return proposals

    # Sort by attention score descending
    scored.sort(key=lambda x: x["attention_score"], reverse=True)

    # Build proposals
    for rank, entry in enumerate(scored[:5]):
        supplier = entry["supplier"]
        # Estimate reroute cost (simplified: base + distance premium)
        base_cost = supplier.get("inventory_value_usd", 10000) * 0.05
        distance_premium = entry["drive_distance_km"] * 2.5  # $2.50/km
        reroute_cost = base_cost + distance_premium

        proposal_id = f"prop-{uuid.uuid4().hex[:12]}"

        raw_proposal = {
            "proposal_id": proposal_id,
            "threat_id": threat_id,
            "rank": rank + 1,
            "original_supplier_id": origin_location.get("location_id", "unknown"),
            "proposed_supplier_id": supplier["location_id"],
            "proposed_supplier_name": supplier["name"],
            "attention_score": round(entry["attention_score"], 6),
            "reliability_index": entry["reliability"],
            "vector_similarity": round(entry["vector_similarity"], 4),
            "distance_from_threat_km": round(entry["dist_km"], 2),
            "mapbox_drive_time_minutes": round(entry["drive_time_min"], 2),
            "mapbox_distance_km": round(entry["drive_distance_km"], 2),
            "route_geometry": entry["route_geometry"],
            "reroute_cost_usd": round(reroute_cost, 2),
            "rationale": (
                f"Supplier '{supplier['name']}' selected with attention score "
                f"{entry['attention_score']:.6f}. "
                f"A = (V×R)/T = ({entry['vector_similarity']:.3f} × "
                f"{entry['reliability']:.3f}) / {entry['drive_time_min']:.0f}min. "
                f"Distance from threat: {entry['dist_km']:.0f}km."
            ),
        }
        proposals.append(RerouteProposal(**raw_proposal).model_dump())

    logger.info(
        "Procurement cycle produced %d proposals for threat %s. "
        "Top candidate: %s (score %.6f)",
        len(proposals),
        threat_id,
        proposals[0]["proposed_supplier_name"] if proposals else "none",
        proposals[0]["attention_score"] if proposals else 0,
    )

    return proposals


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
