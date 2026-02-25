"""Ingestion API — manual trigger + status for NOAA / NASA FIRMS polling."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.core.security import verify_api_key
from app.services.noaa import fetch_noaa_alerts
from app.services.nasa_firms import fetch_firms_fires
from app.services.indexer import index_threats, expire_old_threats
from app.core.events import broadcast

logger = logging.getLogger("aegis.api.ingest")
router = APIRouter(
    prefix="/ingest",
    tags=["ingestion"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/poll")
async def trigger_poll():
    """Manually trigger a full ingestion cycle (NOAA + FIRMS)."""
    await run_in_threadpool(expire_old_threats)

    noaa_threats = []
    try:
        noaa_threats = await fetch_noaa_alerts()
    except Exception as exc:
        logger.error("NOAA ingestion failed: %s", exc)

    firms_threats = []
    try:
        firms_threats = await fetch_firms_fires()
    except Exception as exc:
        logger.error("NASA FIRMS ingestion failed: %s", exc)

    all_threats = noaa_threats + firms_threats
    indexed = await run_in_threadpool(index_threats, all_threats)

    result = {
        "noaa_alerts": len(noaa_threats),
        "firms_clusters": len(firms_threats),
        "indexed": indexed,
    }
    await broadcast("ingest_complete", {
        **result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
    })
    return result


@router.get("/status")
def ingestion_status():
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
