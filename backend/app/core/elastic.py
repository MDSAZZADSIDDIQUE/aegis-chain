"""Elasticsearch client singleton and startup index/policy provisioning."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from elasticsearch import Elasticsearch

from app.core.config import settings

logger = logging.getLogger("aegis.elastic")

_client: Elasticsearch | None = None

# Repository root resolved once at import time
_REPO_ROOT     = Path(__file__).resolve().parents[3]
_MAPPINGS_DIR  = _REPO_ROOT / "elasticsearch" / "mappings"
_ILM_DIR       = _REPO_ROOT / "elasticsearch" / "ilm"
_TEMPLATES_DIR = _REPO_ROOT / "elasticsearch" / "templates"


def get_es_client() -> Elasticsearch:
    global _client
    if _client is None:
        if settings.elastic_cloud_id:
            _client = Elasticsearch(
                cloud_id=settings.elastic_cloud_id,
                api_key=settings.elastic_api_key,
                request_timeout=60,
                retry_on_timeout=True,
                max_retries=3,
            )
        else:
            _client = Elasticsearch(
                hosts=[settings.elastic_url],
                api_key=settings.elastic_api_key,
                request_timeout=60,
                retry_on_timeout=True,
                max_retries=3,
            )
    return _client


def _clean_body_for_serverless(obj: Any) -> None:
    """Recursively strip serverless-incompatible settings/meta from a dict."""
    if isinstance(obj, dict):
        # 1. Strip disallowed settings
        if "settings" in obj and isinstance(obj["settings"], dict):
            s = obj["settings"]
            # Top-level settings keys
            for k in ["index.number_of_shards", "index.number_of_replicas", 
                      "number_of_shards", "number_of_replicas", "index.lifecycle.name"]:
                s.pop(k, None)
            
            # Nested settings.index keys
            if "index" in s and isinstance(s["index"], dict):
                idx = s["index"]
                for k in ["number_of_shards", "number_of_replicas", "lifecycle.name"]:
                    idx.pop(k, None)
        
        # 2. Remove meta descriptions in serverless mode (often cause errors or limits)
        if "meta" in obj:
            obj.pop("meta")

        # 3. Recurse
        for v in list(obj.values()):
            _clean_body_for_serverless(v)
    elif isinstance(obj, list):
        for item in obj:
            _clean_body_for_serverless(item)


async def ensure_indices() -> None:
    """Provision ILM policies, composable index templates, and indices/data-streams.

    Call order matters:
      1. ILM policies    — must exist before templates reference them.
      2. Index templates — must exist before data streams are created.
      3. Regular indices — created only when absent.
      4. supply-latency-logs — created as a TSDS data stream (ILM-managed);
         falls back to a regular TSDS index for older ES versions.
    """
    es = get_es_client()
    info = es.info()
    is_serverless = info.get("version", {}).get("build_flavor") == "serverless"

    # ── 1. ILM policies ──────────────────────────────────────────────────────
    # Serverless does not use /_ilm/policy. Skip if serverless.
    if not is_serverless:
        ilm_files = {
            "supply-latency-logs-ilm": "supply-latency-logs-ilm.json",
        }
        for policy_name, filename in ilm_files.items():
            path = _ILM_DIR / filename
            if not path.exists():
                logger.warning("ILM policy file not found: %s", path)
                continue
            try:
                body = json.loads(path.read_text())
                es.ilm.put_lifecycle(name=policy_name, policy=body["policy"])
                logger.info("ILM policy '%s' created/updated", policy_name)
            except Exception as exc:
                logger.warning("ILM policy '%s' setup failed: %s", policy_name, exc)

    # ── 2. Composable index templates ────────────────────────────────────────
    # Skip templates referencing ILM in serverless mode.
    if not is_serverless:
        template_files = {
            "supply-latency-logs-template": "supply-latency-logs-template.json",
        }
        for template_name, filename in template_files.items():
            path = _TEMPLATES_DIR / filename
            if not path.exists():
                logger.warning("Index template file not found: %s", path)
                continue
            try:
                body = json.loads(path.read_text())
                es.indices.put_index_template(name=template_name, body=body)
                logger.info("Index template '%s' created/updated", template_name)
            except Exception as exc:
                logger.warning("Index template '%s' setup failed: %s", template_name, exc)

    # ── 3. Regular indices ───────────────────────────────────────────────────
    # supply-latency-logs is handled separately below (data stream path).

    index_files = {
        "erp-locations":       "erp-locations.json",
        "weather-threats":     "weather-threats.json",
        "aegis-proposals":     "aegis-proposals.json",
        "supplier-sla-scores": "supplier-sla-scores.json",
        "aegis-execution-log": "aegis-execution-log.json",
        "aegis-ml-results":    "aegis-ml-results.json",
    }

    for index_name, filename in index_files.items():
        if es.indices.exists(index=index_name):
            continue
        body = json.loads((_MAPPINGS_DIR / filename).read_text())
        
        if is_serverless:
            _clean_body_for_serverless(body)

        es.indices.create(index=index_name, body=body)
        logger.info("Index '%s' created", index_name)

    # ── 4. supply-latency-logs — TSDS data stream with ILM ──────────────────
    # Preferred: data stream — ILM rollover automatically manages backing-index
    # time windows so no hard-coded end_time is ever needed.
    # Fallback: regular TSDS index for ES versions that pre-date data stream
    # TSDS support (< 8.7).

    if not es.indices.exists(index="supply-latency-logs"):
        try:
            es.indices.create_data_stream(name="supply-latency-logs")
            logger.info(
                "Data stream 'supply-latency-logs' created "
                "(ILM: supply-latency-logs-ilm, rolls monthly, deletes at 730d)"
            )
        except Exception as exc:
            logger.warning(
                "Data stream creation failed (%s) — "
                "falling back to TSDS index (no ILM rollover)", exc,
            )
            try:
                body = json.loads(
                    (_MAPPINGS_DIR / "supply-latency-logs.json").read_text()
                )
                if is_serverless:
                    _clean_body_for_serverless(body)
                es.indices.create(index="supply-latency-logs", body=body)
                logger.info("Index 'supply-latency-logs' created (fallback path)")
            except Exception as exc2:
                logger.error("supply-latency-logs creation failed: %s", exc2)
