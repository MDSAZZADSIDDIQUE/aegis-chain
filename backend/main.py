"""AegisChain — Autonomous Cognitive Supply Chain Immune System.

FastAPI application entrypoint.  Starts the API server, schedules the
background polling / orchestration loops, and hosts the internal webhook
used by Elastic Workflows to push execution events to connected browsers.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.ingest import router as ingest_router
from app.api.routes import router as core_router, slack_router
from app.api.simulate import router as simulate_router
from app.core.security import verify_api_key
from app.agents.orchestrator import run_full_pipeline
from app.core.config import settings
from app.core.elastic import ensure_indices
from app.core.events import (
    broadcast,
    subscriber_count,
    ws_broadcast,
    ws_connect,
    ws_disconnect,
    ws_client_count,
)
from app.services.noaa import fetch_noaa_alerts
from app.services.nasa_firms import fetch_firms_fires
from app.services.usgs import fetch_usgs_earthquakes
from app.services.indexer import index_threats, expire_old_threats
from app.services.ml_jobs import ensure_ml_jobs

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("aegis")

scheduler = AsyncIOScheduler()


# ── Background task helpers ───────────────────────────────────────────────────

async def scheduled_ingest() -> None:
    """Background task: poll NOAA + FIRMS + USGS, index threats, broadcast to SSE."""
    try:
        expire_old_threats()
        noaa  = await fetch_noaa_alerts()
        firms = await fetch_firms_fires()
        usgs  = await fetch_usgs_earthquakes()
        total = await index_threats(noaa + firms + usgs)
        logger.info(
            "Scheduled ingest: %d NOAA, %d FIRMS, %d USGS, %d indexed",
            len(noaa), len(firms), len(usgs), total,
        )
        await broadcast("ingest_complete", {
            "noaa_alerts":    len(noaa),
            "firms_clusters": len(firms),
            "usgs_quakes":    len(usgs),
            "indexed":        total,
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error("Scheduled ingest failed: %s", exc)


async def scheduled_pipeline() -> None:
    """Background task: run the full 3-agent pipeline, broadcast to SSE."""
    try:
        result = await run_full_pipeline(emit=ws_broadcast)
        logger.info(
            "Scheduled pipeline: %d threats correlated, %d proposals, %d actions",
            result["watcher"].get("threat_correlations", 0),
            len(result["procurement"]),
            len(result["actions_taken"]),
        )
        await broadcast("pipeline_complete", {
            "threats_correlated": result["watcher"].get("threat_correlations", 0),
            "proposals":          len(result["procurement"]),
            "actions_taken":      len(result["actions_taken"]),
            "timestamp":          datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error("Scheduled pipeline failed: %s", exc)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("AegisChain starting up...")

    await ensure_indices()
    await ensure_ml_jobs()

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


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="AegisChain",
    description="Autonomous Cognitive Supply Chain Immune System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(core_router)
app.include_router(simulate_router)
app.include_router(slack_router)  # Slack HMAC auth — no AegisChain key required


# ── System routes ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    from app.core.elastic import get_es_client
    try:
        info       = get_es_client().info()
        es_status  = "connected"
        es_version = info["version"]["number"]
    except Exception:
        es_status  = "disconnected"
        es_version = "unknown"

    return {
        "status":          "ok",
        "service":         "aegis-chain",
        "elasticsearch":   es_status,
        "es_version":      es_version,
        "sse_subscribers": subscriber_count(),
        "ws_clients":      ws_client_count(),
    }


# ── WebSocket: real-time pipeline progress ────────────────────────────────────

@app.websocket("/ws/pipeline")
async def ws_pipeline(
    websocket: WebSocket,
    _: None = Depends(verify_api_key),
):
    """Stream per-agent progress events to the dashboard as the pipeline runs.

    The browser connects once on mount.  Progress events arrive whenever the
    pipeline executes (manual trigger via POST /pipeline/run or the scheduler).
    A 20-second ping keeps the connection alive through proxies.

    Event shape (example)::

        {"agent": "watcher",     "status": "complete", "threats": 3, "at_risk": 2}
        {"agent": "procurement", "status": "complete", "proposals": 5}
        {"agent": "auditor",     "status": "complete", "approved": 3, "hitl": 1, "rejected": 1}
        {"agent": "pipeline",    "status": "complete", "actions": 4}
    """
    await websocket.accept()
    ws_connect(websocket)
    logger.info("WS /ws/pipeline client connected")
    try:
        while True:
            try:
                # Wait up to 20 s for a client message (unused currently, future-proof)
                await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
            except asyncio.TimeoutError:
                # Send keepalive ping so the connection doesn't idle-close
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        ws_disconnect(websocket)
        logger.info("WS /ws/pipeline client disconnected")


@app.post("/pipeline/run", dependencies=[Depends(verify_api_key)])
async def trigger_pipeline():
    """Manually trigger the full 3-agent pipeline.
    Broadcasts pipeline_complete to all SSE subscribers on completion.
    Streams per-agent progress to all /ws/pipeline WebSocket clients.
    """
    result = await run_full_pipeline(emit=ws_broadcast)
    await broadcast("pipeline_complete", {
        "threats_correlated": result["watcher"].get("threat_correlations", 0),
        "proposals":          len(result["procurement"]),
        "actions_taken":      len(result["actions_taken"]),
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "source":             "manual",
    })
    return result


# ── Internal webhook ──────────────────────────────────────────────────────────

@app.post("/internal/execution-event", dependencies=[Depends(verify_api_key)])
async def internal_execution_event(request: Request):
    """Webhook called by the Elastic Workflow notify_dashboard step.

    When the auto-execution Workflow completes a reroute it POSTs here.
    This handler:
      1. Persists the event to the ``aegis-execution-log`` index (dynamic
         mapping — ES auto-creates on first write).
      2. Broadcasts an ``execution_event`` to every connected SSE client so
         the approved route appears on the globe without a page refresh.

    Minimum expected body::

        {
            "proposal_id": "prop-abc123",
            "event_type":  "reroute_executed",
            "threat_id":   "threat-xyz",   (optional)
            "timestamp":   "2026-02-23T..."  (optional)
        }
    """
    from app.core.elastic import get_es_client

    body: dict[str, Any] = await request.json()

    # Persist to execution log
    es = get_es_client()
    log_doc: dict[str, Any] = {
        "@timestamp":  datetime.now(timezone.utc).isoformat(),
        "event_type":  body.get("event_type", "reroute_executed"),
        "proposal_id": body.get("proposal_id"),
        "threat_id":   body.get("threat_id"),
        "source":      body.get("source", "elastic_workflow"),
        "payload":     body,
    }
    try:
        es.index(index="aegis-execution-log", document=log_doc)
    except Exception as exc:
        logger.warning("Failed to persist execution event to ES: %s", exc)

    # Push to every SSE subscriber — this is the step that makes the route
    # appear on the globe in real-time without a 30-second polling wait
    notified = await broadcast("execution_event", body)
    logger.info(
        "Execution event '%s' (proposal=%s) → %d SSE subscriber(s) notified",
        body.get("event_type", "?"),
        body.get("proposal_id", "?"),
        notified,
    )

    return {
        "status":               "ok",
        "subscribers_notified": notified,
        "total_subscribers":    subscriber_count(),
    }
