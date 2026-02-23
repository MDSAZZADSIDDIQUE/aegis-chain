"""AegisChain — Autonomous Cognitive Supply Chain Immune System.

FastAPI application entrypoint. Starts the API server and schedules
the background polling/orchestration loops.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ingest import router as ingest_router
from app.api.routes import router as core_router
from app.agents.orchestrator import run_full_pipeline
from app.core.config import settings
from app.core.elastic import ensure_indices
from app.services.noaa import fetch_noaa_alerts
from app.services.nasa_firms import fetch_firms_fires
from app.services.indexer import index_threats, expire_old_threats

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("aegis")

scheduler = AsyncIOScheduler()


async def scheduled_ingest() -> None:
    """Background task: poll NOAA + FIRMS and index threats."""
    try:
        expire_old_threats()
        noaa = await fetch_noaa_alerts()
        firms = await fetch_firms_fires()
        total = index_threats(noaa + firms)
        logger.info("Scheduled ingest: %d NOAA, %d FIRMS, %d indexed", len(noaa), len(firms), total)
    except Exception as exc:
        logger.error("Scheduled ingest failed: %s", exc)


async def scheduled_pipeline() -> None:
    """Background task: run the full 3-agent pipeline."""
    try:
        result = await run_full_pipeline()
        logger.info(
            "Scheduled pipeline: %d threats correlated, %d proposals, %d actions",
            result["watcher"].get("threat_correlations", 0),
            len(result["procurement"]),
            len(result["actions_taken"]),
        )
    except Exception as exc:
        logger.error("Scheduled pipeline failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("AegisChain starting up...")

    # Ensure Elasticsearch indices exist
    await ensure_indices()

    # Schedule background jobs
    scheduler.add_job(
        scheduled_ingest,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="ingest_poll",
        name="NOAA/FIRMS Ingestion",
    )
    scheduler.add_job(
        scheduled_pipeline,
        "interval",
        seconds=settings.poll_interval_seconds + 60,  # offset from ingest
        id="agent_pipeline",
        name="Agent Pipeline",
    )
    scheduler.start()
    logger.info(
        "Schedulers started (ingest every %ds, pipeline every %ds)",
        settings.poll_interval_seconds,
        settings.poll_interval_seconds + 60,
    )

    yield

    scheduler.shutdown()
    logger.info("AegisChain shut down.")


app = FastAPI(
    title="AegisChain",
    description="Autonomous Cognitive Supply Chain Immune System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(core_router)


@app.get("/health")
async def health():
    from app.core.elastic import get_es_client
    try:
        info = get_es_client().info()
        es_status = "connected"
        es_version = info["version"]["number"]
    except Exception:
        es_status = "disconnected"
        es_version = "unknown"

    return {
        "status": "ok",
        "service": "aegis-chain",
        "elasticsearch": es_status,
        "es_version": es_version,
    }


@app.post("/pipeline/run")
async def trigger_pipeline():
    """Manually trigger the full 3-agent pipeline."""
    result = await run_full_pipeline()
    return result
