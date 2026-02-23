"""Ingestion API — manual trigger + status for NOAA / NASA FIRMS polling."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.services.noaa import fetch_noaa_alerts
from app.services.nasa_firms import fetch_firms_fires
from app.services.indexer import index_threats, expire_old_threats

logger = logging.getLogger("aegis.api.ingest")
router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("/poll")
async def trigger_poll():
    """Manually trigger a full ingestion cycle (NOAA + FIRMS)."""
    expire_old_threats()

    noaa_threats = await fetch_noaa_alerts()
    firms_threats = await fetch_firms_fires()

    all_threats = noaa_threats + firms_threats
    indexed = index_threats(all_threats)

    return {
        "noaa_alerts": len(noaa_threats),
        "firms_clusters": len(firms_threats),
        "indexed": indexed,
    }


@router.get("/status")
async def ingestion_status():
    """Return counts of currently active threats by source."""
    from app.core.elastic import get_es_client

    es = get_es_client()
    resp = es.search(
        index="weather-threats",
        body={
            "size": 0,
            "query": {"term": {"status": "active"}},
            "aggs": {
                "by_source": {"terms": {"field": "source"}},
                "by_event": {"terms": {"field": "event_type"}},
                "by_severity": {"terms": {"field": "severity"}},
            },
        },
    )
    aggs = resp.get("aggregations", {})
    return {
        "active_threats": resp["hits"]["total"]["value"],
        "by_source": {
            b["key"]: b["doc_count"]
            for b in aggs.get("by_source", {}).get("buckets", [])
        },
        "by_event": {
            b["key"]: b["doc_count"]
            for b in aggs.get("by_event", {}).get("buckets", [])
        },
        "by_severity": {
            b["key"]: b["doc_count"]
            for b in aggs.get("by_severity", {}).get("buckets", [])
        },
    }
