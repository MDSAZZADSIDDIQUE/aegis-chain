#!/usr/bin/env python3
"""Compute SLA compatibility scores for every ERP location.

Populates the ``supplier-sla-scores`` LOOKUP index so ES|QL LOOKUP JOIN
works without a per-query kNN round-trip to the Python agent.

Strategy (in priority order)
-----------------------------
1.  kNN on ``contract_sla_vector`` via the .multilingual-e5-small inference
    endpoint — exact semantic cosine match to the reference SLA query.
2.  BM25 ``match`` on ``contract_sla`` free-text — always available, fast.
3.  ``reliability_index * 0.65`` proxy — for locations with no SLA text.

All three sources are blended into a single normalised [0, 1] score that is
bulk-indexed with ``location_id`` as the document ``_id`` (idempotent re-runs).

Usage
-----
    python -m scripts.compute_sla_scores              # incremental upsert
    python -m scripts.compute_sla_scores --force      # drop + recreate index
    python -m scripts.compute_sla_scores --dry-run    # compute only, no writes
    python -m scripts.compute_sla_scores --query "..."  # override SLA query

ES|QL LOOKUP JOIN (requires ES 8.15+, lookup index mode)
---------------------------------------------------------
After this script runs, procurement and the chat-to-map endpoint can do:

    FROM erp-locations
    | LOOKUP JOIN `supplier-sla-scores` ON location_id
    | EVAL score = reliability_index * COALESCE(sla_score, 0.5)
    | SORT score DESC

Tiers
-----
    platinum ≥ 0.80 | gold ≥ 0.60 | silver ≥ 0.40 | bronze < 0.40
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── sys.path bootstrap ────────────────────────────────────────────────────────
# Allows `from app.core.*` imports when run directly from repo root or
# as `python -m scripts.compute_sla_scores` from the backend directory.
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.core.config import settings  # noqa: E402
from app.core.elastic import get_es_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("aegis.scripts.sla_scores")

# ── Constants ─────────────────────────────────────────────────────────────────

SLA_SCORES_INDEX = "supplier-sla-scores"
MAPPINGS_DIR = _root / "elasticsearch" / "mappings"

_REFERENCE_QUERY = (
    "guaranteed delivery windows high fill rate penalty clauses "
    "climate resilience priority allocation 99 percent uptime force majeure"
)

_TIERS: list[tuple[float, str]] = [
    (0.80, "platinum"),
    (0.60, "gold"),
    (0.40, "silver"),
    (0.00, "bronze"),
]

# kNN scores cap — BM25 normalised scores are capped below this so platinum
# and gold tiers are reserved for genuine semantic kNN matches.
_BM25_SCALE_CAP = 0.79


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tier(score: float) -> str:
    for threshold, name in _TIERS:
        if score >= threshold:
            return name
    return "bronze"


def _recreate_index(es, dry_run: bool) -> None:
    if es.indices.exists(index=SLA_SCORES_INDEX):
        if not dry_run:
            es.indices.delete(index=SLA_SCORES_INDEX)
        logger.info("%sDeleted existing index %s", "[DRY-RUN] Would have " if dry_run else "", SLA_SCORES_INDEX)

    mapping_path = MAPPINGS_DIR / "supplier-sla-scores.json"
    body = json.loads(mapping_path.read_text())
    if not dry_run:
        es.indices.create(index=SLA_SCORES_INDEX, body=body)
    logger.info("%sCreated index %s", "[DRY-RUN] Would have " if dry_run else "", SLA_SCORES_INDEX)


def _ensure_index_exists(es, dry_run: bool) -> None:
    if not es.indices.exists(index=SLA_SCORES_INDEX):
        _recreate_index(es, dry_run=dry_run)


def _fetch_all_locations(es) -> list[dict[str, Any]]:
    """Page through erp-locations with search_after."""
    locations: list[dict[str, Any]] = []

    resp = es.search(
        index="erp-locations",
        body={
            "size": 500,
            "query": {"match_all": {}},
            "sort": [{"location_id": "asc"}],
            "_source": ["location_id", "name", "type", "reliability_index", "contract_sla"],
        },
    )
    hits = resp["hits"]["hits"]
    locations.extend(h["_source"] for h in hits)

    while len(hits) == 500:
        last_sort = hits[-1]["sort"]
        resp = es.search(
            index="erp-locations",
            body={
                "size": 500,
                "query": {"match_all": {}},
                "sort": [{"location_id": "asc"}],
                "search_after": last_sort,
                "_source": ["location_id", "name", "type", "reliability_index", "contract_sla"],
            },
        )
        hits = resp["hits"]["hits"]
        locations.extend(h["_source"] for h in hits)

    logger.info("Fetched %d ERP locations total", len(locations))
    return locations


def _knn_scores(es, query_text: str, n: int) -> dict[str, float]:
    """
    Run one kNN search against contract_sla_vector with the reference query.
    Returns a dict of {location_id: normalised_score [0,1]}.
    Returns {} if the model endpoint is unavailable or vectors are empty.
    """
    try:
        resp = es.search(
            index="erp-locations",
            body={
                "size": n,
                "knn": {
                    "field": "contract_sla_vector",
                    "query_vector_builder": {
                        "text_embedding": {
                            "model_id": ".multilingual-e5-small",
                            "model_text": query_text,
                        }
                    },
                    "k": n,
                    "num_candidates": max(n * 2, 100),
                },
                "_source": ["location_id"],
            },
        )
        raw: dict[str, float] = {
            h["_source"]["location_id"]: h["_score"]
            for h in resp["hits"]["hits"]
        }
        if not raw:
            return {}
        max_s = max(raw.values())
        return {k: v / max_s for k, v in raw.items()} if max_s > 0 else {}
    except Exception as exc:
        logger.warning(
            "kNN semantic search unavailable (no .multilingual-e5-small endpoint?). "
            "Falling back to BM25. Reason: %s", exc,
        )
        return {}


def _bm25_scores(es, query_text: str, n: int) -> dict[str, float]:
    """
    BM25 match query on contract_sla free-text.
    Returns {} on failure or if no documents have SLA text.
    """
    try:
        resp = es.search(
            index="erp-locations",
            body={
                "size": n,
                "query": {
                    "match": {
                        "contract_sla": {
                            "query": query_text,
                            "operator": "or",
                            "minimum_should_match": "30%",
                        }
                    }
                },
                "_source": ["location_id"],
            },
        )
        hits = resp["hits"]["hits"]
        if not hits:
            return {}
        max_s = max(h["_score"] for h in hits)
        if max_s <= 0:
            return {}
        # Scale BM25 to [0, _BM25_SCALE_CAP] — below genuine kNN range.
        return {
            h["_source"]["location_id"]: (h["_score"] / max_s) * _BM25_SCALE_CAP
            for h in hits
        }
    except Exception as exc:
        logger.warning("BM25 SLA match failed: %s", exc)
        return {}


# ── Core scoring ──────────────────────────────────────────────────────────────

def compute_scores(
    locations: list[dict[str, Any]],
    knn: dict[str, float],
    bm25: dict[str, float],
) -> list[dict[str, Any]]:
    """
    Blend kNN / BM25 / reliability-proxy into one [0,1] score per location.

    Priority:
      1. kNN score   — kept as-is (already [0,1] after normalisation)
      2. BM25 score  — capped at _BM25_SCALE_CAP (below platinum/gold)
      3. proxy       — reliability_index * 0.65 (honest low-confidence default)
    """
    now = datetime.now(timezone.utc).isoformat()
    docs: list[dict[str, Any]] = []

    for loc in locations:
        loc_id = loc["location_id"]

        if loc_id in knn:
            score  = knn[loc_id]
            method = "knn"
        elif loc_id in bm25:
            score  = bm25[loc_id]
            method = "bm25"
        else:
            score  = min(loc.get("reliability_index", 0.5) * 0.65, 0.65)
            method = "proxy"

        score = round(min(max(score, 0.0), 1.0), 6)

        docs.append({
            "location_id": loc_id,
            "sla_score":   score,
            "sla_tier":    _tier(score),
            "sla_method":  method,
            "computed_at": now,
            "@timestamp":  now,
        })

    return docs


def _bulk_index(es, docs: list[dict[str, Any]], dry_run: bool) -> int:
    if dry_run:
        for d in docs[:5]:
            logger.info("[DRY-RUN] %s", d)
        if len(docs) > 5:
            logger.info("[DRY-RUN] … and %d more", len(docs) - 5)
        return 0

    from elasticsearch.helpers import bulk

    actions = [
        {
            "_index":  SLA_SCORES_INDEX,
            "_id":     doc["location_id"],
            "_source": doc,
        }
        for doc in docs
    ]
    success, errors = bulk(es, actions, raise_on_error=False)
    if errors:
        logger.error("%d bulk errors: %s", len(errors), errors[:3])
    return success


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and recreate supplier-sla-scores before writing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute scores and print a preview; do not write to Elasticsearch.",
    )
    parser.add_argument(
        "--query",
        default=_REFERENCE_QUERY,
        metavar="TEXT",
        help="Override the reference SLA query used for scoring.",
    )
    args = parser.parse_args()

    es = get_es_client()

    if args.force:
        _recreate_index(es, dry_run=args.dry_run)
    else:
        _ensure_index_exists(es, dry_run=args.dry_run)

    locations = _fetch_all_locations(es)
    if not locations:
        logger.error("No ERP locations found — run seed_demo_data.py first.")
        sys.exit(1)

    n = len(locations)

    logger.info(
        "Attempting kNN semantic search (requires .multilingual-e5-small endpoint)…"
    )
    knn = _knn_scores(es, args.query, n)
    logger.info(
        "kNN: %d / %d locations scored  (%.0f%%)",
        len(knn), n, 100 * len(knn) / n,
    )

    remaining = n - len(knn)
    bm25: dict[str, float] = {}
    if remaining > 0:
        logger.info("Running BM25 fallback for %d location(s) without kNN scores…", remaining)
        bm25_raw = _bm25_scores(es, args.query, n)
        # Only use BM25 for locations that kNN didn't cover
        bm25 = {k: v for k, v in bm25_raw.items() if k not in knn}
        logger.info("BM25:  %d additional location(s) scored", len(bm25))

    docs = compute_scores(locations, knn, bm25)

    # ── Summary table ────────────────────────────────────────────────────────
    tiers:   dict[str, int] = {}
    methods: dict[str, int] = {}
    for d in docs:
        tiers[d["sla_tier"]]     = tiers.get(d["sla_tier"], 0) + 1
        methods[d["sla_method"]] = methods.get(d["sla_method"], 0) + 1

    logger.info(
        "Score summary — tiers: platinum=%d gold=%d silver=%d bronze=%d | "
        "methods: knn=%d bm25=%d proxy=%d",
        tiers.get("platinum", 0), tiers.get("gold", 0),
        tiers.get("silver", 0),   tiers.get("bronze", 0),
        methods.get("knn", 0), methods.get("bm25", 0), methods.get("proxy", 0),
    )

    indexed = _bulk_index(es, docs, dry_run=args.dry_run)
    if not args.dry_run:
        logger.info(
            "Indexed %d SLA score document(s) → %s  "
            "(ES|QL LOOKUP JOIN is now unblocked)",
            indexed, SLA_SCORES_INDEX,
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()
