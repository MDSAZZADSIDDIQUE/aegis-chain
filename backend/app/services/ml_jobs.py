"""Elasticsearch ML anomaly detection job provisioner.

Reads job definitions from ``elasticsearch/ml/*.json`` and ensures they
exist in the cluster on startup.  If a job already exists it is left
untouched; if the cluster does not support ML (e.g. Serverless / Basic
license) the module degrades gracefully with a warning.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.elastic import get_es_client

logger = logging.getLogger("aegis.ml_jobs")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ML_DIR = _REPO_ROOT / "elasticsearch" / "ml"


async def ensure_ml_jobs() -> None:
    """Provision ML anomaly detection jobs and their datafeeds.

    Safe to call on every startup — idempotent.  Jobs that already exist
    are silently skipped.  If the cluster doesn't support ML the entire
    function is a no-op.
    """
    es = get_es_client()

    # Pre-flight: check ML availability
    try:
        license_info = await asyncio.to_thread(es.license.get)
        license_type = (
            license_info.get("license", {}).get("type", "").lower()
        )
        # ML requires at least trial/platinum/enterprise
        if license_type in ("basic", "standard"):
            logger.info(
                "ES license '%s' does not include ML — skipping job provisioning",
                license_type,
            )
            return
    except Exception:
        # Can't check license — try anyway (serverless may differ)
        pass

    # Discover job definition files
    if not _ML_DIR.exists():
        logger.warning("ML definitions directory not found: %s", _ML_DIR)
        return

    job_files = sorted(_ML_DIR.glob("*.json"))
    if not job_files:
        logger.info("No ML job definitions found in %s", _ML_DIR)
        return

    for path in job_files:
        try:
            spec: dict[str, Any] = json.loads(path.read_text())
            job_id = spec.get("job_id")
            if not job_id:
                logger.warning("ML file %s has no job_id — skipping", path.name)
                continue

            await _ensure_job(es, job_id, spec)
        except Exception as exc:
            logger.error("Failed to provision ML job from %s: %s", path.name, exc)


async def _ensure_job(es: Any, job_id: str, spec: dict[str, Any]) -> None:
    """Create an ML anomaly detection job + datafeed if not already present."""

    # Check if job already exists
    try:
        await asyncio.to_thread(es.ml.get_jobs, job_id=job_id)
        logger.info("ML job '%s' already exists — skipping", job_id)
        return
    except Exception:
        pass  # 404 = doesn't exist yet → create it

    # Extract datafeed config (separate API call)
    datafeed_cfg = spec.pop("datafeed_config", None)
    custom = spec.pop("custom_settings", None)

    # Create job
    try:
        body = {
            "description": spec.get("description", ""),
            "analysis_config": spec["analysis_config"],
            "data_description": spec.get("data_description", {"time_field": "@timestamp"}),
            "analysis_limits": spec.get("analysis_limits", {}),
            "results_index_name": spec.get("results_index_name", "shared"),
        }
        if custom:
            body["custom_settings"] = custom

        await asyncio.to_thread(es.ml.put_job, job_id=job_id, body=body)
        logger.info("ML job '%s' created", job_id)
    except Exception as exc:
        logger.error("Failed to create ML job '%s': %s", job_id, exc)
        return

    # Create datafeed
    if datafeed_cfg:
        datafeed_id = datafeed_cfg.pop("datafeed_id", f"datafeed-{job_id}")
        try:
            await asyncio.to_thread(
                es.ml.put_datafeed,
                datafeed_id=datafeed_id,
                body={**datafeed_cfg, "job_id": job_id},
            )
            logger.info("ML datafeed '%s' created for job '%s'", datafeed_id, job_id)
        except Exception as exc:
            logger.error(
                "Failed to create datafeed '%s' for ML job '%s': %s",
                datafeed_id, job_id, exc,
            )
            return

    # Open job and start datafeed
    try:
        await asyncio.to_thread(es.ml.open_job, job_id=job_id)
        logger.info("ML job '%s' opened", job_id)
    except Exception as exc:
        logger.warning("Failed to open ML job '%s': %s", job_id, exc)

    if datafeed_cfg:
        datafeed_id = datafeed_cfg.get("datafeed_id", f"datafeed-{job_id}")
        # Re-construct the ID since we popped it
        actual_feed_id = f"datafeed-{job_id}"
        try:
            await asyncio.to_thread(
                es.ml.start_datafeed,
                datafeed_id=actual_feed_id,
                body={"start": "now-7d"},
            )
            logger.info("ML datafeed '%s' started (lookback: 7d)", actual_feed_id)
        except Exception as exc:
            logger.warning("Failed to start datafeed '%s': %s", actual_feed_id, exc)
