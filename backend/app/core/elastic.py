"""Elasticsearch client singleton."""

from __future__ import annotations

from elasticsearch import Elasticsearch

from app.core.config import settings

_client: Elasticsearch | None = None


def get_es_client() -> Elasticsearch:
    global _client
    if _client is None:
        if settings.elastic_cloud_id:
            _client = Elasticsearch(
                cloud_id=settings.elastic_cloud_id,
                api_key=settings.elastic_api_key,
                request_timeout=30,
            )
        else:
            _client = Elasticsearch(
                hosts=[settings.elastic_url],
                api_key=settings.elastic_api_key,
                request_timeout=30,
            )
    return _client


async def ensure_indices() -> None:
    """Create indices if they don't already exist."""
    import json
    from pathlib import Path

    es = get_es_client()
    mappings_dir = Path(__file__).resolve().parents[3] / "elasticsearch" / "mappings"

    index_files = {
        "erp-locations": "erp-locations.json",
        "weather-threats": "weather-threats.json",
        "supply-latency-logs": "supply-latency-logs.json",
    }

    for index_name, filename in index_files.items():
        if not es.indices.exists(index=index_name):
            body = json.loads((mappings_dir / filename).read_text())
            es.indices.create(index=index_name, body=body)
