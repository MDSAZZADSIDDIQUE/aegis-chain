"""Elasticsearch bulk indexer for weather-threat documents."""

from __future__ import annotations

import logging
from typing import Any

from elasticsearch.helpers import bulk

from app.core.elastic import get_es_client

logger = logging.getLogger("aegis.indexer")


def index_threats(threats: list[dict[str, Any]]) -> int:
    """Bulk-index weather-threat documents. Returns count of indexed docs."""
    if not threats:
        return 0

    es = get_es_client()

    actions = []
    for doc in threats:
        actions.append({
            "_index": "weather-threats",
            "_id": doc["threat_id"],
            "_source": doc,
        })

    success, errors = bulk(es, actions, raise_on_error=False, refresh="wait_for")
    if errors:
        logger.error("Bulk indexing errors: %s", errors)

    logger.info("Indexed %d weather-threat docs", success)
    return success


def expire_old_threats() -> int:
    """Mark expired NOAA alerts as status=expired using update_by_query."""
    es = get_es_client()
    resp = es.update_by_query(
        index="weather-threats",
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"status": "active"}},
                        {"range": {"expires": {"lt": "now"}}},
                    ]
                }
            },
            "script": {
                "source": "ctx._source.status = 'expired'",
                "lang": "painless",
            },
        },
        refresh=True,
    )
    updated = resp.get("updated", 0)
    if updated:
        logger.info("Expired %d old threat documents", updated)
    return updated


def update_reliability_index(
    supplier_id: str,
    new_reliability: float,
) -> None:
    """Update a supplier's reliability_index in erp-locations."""
    es = get_es_client()
    es.update_by_query(
        index="erp-locations",
        body={
            "query": {"term": {"location_id": supplier_id}},
            "script": {
                "source": "ctx._source.reliability_index = params.ri",
                "lang": "painless",
                "params": {"ri": max(0.0, min(1.0, new_reliability))},
            },
        },
        refresh=True,
    )
    logger.info(
        "Updated reliability_index for %s to %.4f", supplier_id, new_reliability
    )
