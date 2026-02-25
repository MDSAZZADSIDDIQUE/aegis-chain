"""Proposal persistence — aegis-proposals Elasticsearch index.

All CRUD for reroute proposals is centralised here so that both the REST
API (routes.py) and the agent pipeline (orchestrator.py) share the same
persistence path.  The index uses proposal_id as the document _id, making
upserts idempotent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from elasticsearch import NotFoundError

from app.core.elastic import get_es_client

INDEX = "aegis-proposals"
logger = logging.getLogger("aegis.services.proposals")


# ── Write operations ──────────────────────────────────────────────────────────

def upsert_proposal(doc: dict[str, Any]) -> None:
    """Index a proposal document, using proposal_id as the _id (idempotent).

    Automatically sets created_at / @timestamp on first insert and
    updated_at on every call.
    """
    es = get_es_client()
    now = datetime.now(timezone.utc).isoformat()

    doc.setdefault("created_at", now)
    doc.setdefault("@timestamp", doc["created_at"])
    doc.setdefault("hitl_status", "awaiting_approval")
    doc["updated_at"] = now

    try:
        es.index(index=INDEX, id=doc["proposal_id"], document=doc)
    except Exception as exc:
        logger.error("Failed to upsert proposal %s: %s", doc.get("proposal_id"), exc)
        raise


def update_proposal(proposal_id: str, fields: dict[str, Any]) -> None:
    """Partial update — only the supplied fields are changed.

    Args:
        proposal_id: Document _id in aegis-proposals.
        fields: Dict of field names → new values.  updated_at is injected
                automatically.
    Raises:
        NotFoundError: If the proposal does not exist.
    """
    es = get_es_client()
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        es.update(index=INDEX, id=proposal_id, doc=fields)
    except NotFoundError:
        logger.warning("update_proposal: proposal %s not found", proposal_id)
        raise
    except Exception as exc:
        logger.error("Failed to update proposal %s: %s", proposal_id, exc)
        raise


# ── Read operations ───────────────────────────────────────────────────────────

def get_proposal(proposal_id: str) -> dict[str, Any] | None:
    """Fetch a single proposal by its ID.

    Returns:
        The _source document, or None if the proposal does not exist.
    """
    es = get_es_client()
    try:
        resp = es.get(index=INDEX, id=proposal_id)
        return resp["_source"]
    except NotFoundError:
        return None
    except Exception as exc:
        logger.error("Failed to get proposal %s: %s", proposal_id, exc)
        raise


def list_proposals(
    statuses: list[str] | None = None,
    size: int = 100,
    from_: int = 0,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    """Query proposals with optional status filter and pagination.

    Args:
        statuses:   If provided, only documents whose hitl_status is in this
                    list are returned.  None means return all.
        size:       Maximum documents to return (page size).
        from_:      Zero-based offset for pagination.
        sort_by:    Field to sort by (default: created_at).
        sort_order: "asc" or "desc" (default: "desc").

    Returns:
        Tuple of (list_of_source_docs, total_hit_count).
    """
    es = get_es_client()

    query: dict[str, Any] = (
        {"terms": {"hitl_status": statuses}} if statuses else {"match_all": {}}
    )

    try:
        resp = es.search(
            index=INDEX,
            body={
                "query": query,
                "sort": [{sort_by: {"order": sort_order}}],
                "size": size,
                "from": from_,
            },
        )
    except NotFoundError:
        # Index may not exist on first run before ensure_indices()
        return [], 0
    except Exception as exc:
        logger.error("Failed to list proposals (statuses=%s): %s", statuses, exc)
        raise

    docs = [h["_source"] for h in resp["hits"]["hits"]]
    total: int = resp["hits"]["total"]["value"]
    return docs, total
