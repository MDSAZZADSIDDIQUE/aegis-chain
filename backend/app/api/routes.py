"""Core API routes — Mapbox routing, Slack HITL, RL updates, dashboard state, chat."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import verify_api_key
from app.core.elastic import get_es_client
from app.models.schemas import (
    AuditVerdict,
    ChatQuery,
    ChatResponse,
    DashboardState,
    ERPLocationCreated,
    ERPLocationUpsert,
    MapboxRouteRequest,
    MapboxRouteResponse,
    RerouteProposal,
    RLUpdate,
    SlackAction,
)
from app.services.mapbox import get_route
from app.services.slack import send_hitl_approval_request, verify_slack_signature
from app.services.indexer import update_reliability_index
from app.services.claude_chat import (
    classify_intent,
    explain_results,
    stream_explanation,
    ESQL_SUPPLIER_RANKING,
    ESQL_SUPPLIER_RANKING_FALLBACK,
    ESQL_RISK_ASSESSMENT,
    ESQL_REROUTE_PROPOSALS,
)
from app.services.proposals import (
    upsert_proposal,
    get_proposal as _get_proposal,
    update_proposal as _update_proposal,
    list_proposals as _list_proposals,
)

logger = logging.getLogger("aegis.api.routes")

# All routes on this router require a valid X-AegisChain-Key header
# (no-op when AEGIS_API_KEY is unset — dev mode).
router = APIRouter(tags=["core"], dependencies=[Depends(verify_api_key)])

# Slack interactive callbacks authenticate via HMAC request-signature instead;
# they must NOT carry the AegisChain API key dependency.
slack_router = APIRouter(tags=["core"])


# ─────────────────────────────────────────────────────────────────────
# Mapbox Route
# ─────────────────────────────────────────────────────────────────────
@router.post("/route", response_model=MapboxRouteResponse)
async def compute_route(req: MapboxRouteRequest):
    """Agent 2 calls this to get real Mapbox drive-time around a hazard."""
    try:
        result = await get_route(
            origin_lon=req.origin_lon,
            origin_lat=req.origin_lat,
            dest_lon=req.destination_lon,
            dest_lat=req.destination_lat,
            avoid_polygon=req.avoid_polygon,
        )
        return MapboxRouteResponse(**result)
    except Exception as exc:
        logger.error("Mapbox route error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────
# ERP Locations — operator node management
# ─────────────────────────────────────────────────────────────────────

@router.post("/erp-locations", response_model=ERPLocationCreated, status_code=201)
def upsert_erp_location(body: ERPLocationUpsert):
    """Add or update an ERP node (supplier, warehouse, distribution centre, port).

    If ``location_id`` is omitted a new node is created with a generated ID.
    If ``location_id`` is provided the existing document is replaced (full upsert).
    The document is immediately visible to the watcher and procurement agents.
    """
    es = get_es_client()

    is_update = body.location_id is not None
    location_id = body.location_id or f"erp-{uuid.uuid4().hex[:8]}"

    doc: dict[str, Any] = {
        "location_id": location_id,
        "name": body.name,
        "type": body.type,
        "coordinates": {"lat": body.lat, "lon": body.lon},
        "inventory_value_usd": body.inventory_value_usd,
        "reliability_index": body.reliability_index,
        "avg_lead_time_hours": body.avg_lead_time_hours,
        "active": body.active,
        "tags": body.tags,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if body.contract_sla:
        doc["contract_sla"] = body.contract_sla
    if body.capacity_units is not None:
        doc["capacity_units"] = body.capacity_units
    if body.region:
        doc["region"] = body.region
    if body.country_code:
        doc["country_code"] = body.country_code
    if body.address:
        doc["address"] = body.address

    es.index(
        index="erp-locations",
        id=location_id,
        document=doc,
        refresh="wait_for",
    )
    logger.info("ERP location %s %s", location_id, "updated" if is_update else "created")
    return ERPLocationCreated(
        status="updated" if is_update else "created",
        location_id=location_id,
    )


# ─────────────────────────────────────────────────────────────────────
# Reroute Proposals  (Agent 2 → Agent 3 pipeline)
# ─────────────────────────────────────────────────────────────────────

@router.post("/proposals")
def submit_proposal(proposal: RerouteProposal):
    """Agent 2 submits a reroute proposal for Agent 3 review.
    Persists to aegis-proposals index; idempotent on proposal_id.
    """
    doc = {**proposal.model_dump(), "hitl_status": "pending"}
    upsert_proposal(doc)
    logger.info("Proposal %s submitted and persisted", proposal.proposal_id)
    return {"status": "received", "proposal_id": proposal.proposal_id}


@router.get("/proposals")
def list_proposals_endpoint(
    status: str | None = Query(
        None,
        description="Filter by hitl_status: pending | awaiting_approval | "
                    "auto_approved | approved | rejected",
    ),
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(50, ge=1, le=500, description="Documents per page"),
):
    """Paginated list of all proposals, optionally filtered by HITL status."""
    statuses = [status] if status else None
    proposals, total = _list_proposals(
        statuses=statuses,
        size=size,
        from_=(page - 1) * size,
    )
    return {"proposals": proposals, "total": total, "page": page, "size": size}


@router.get("/proposals/{proposal_id}")
def get_proposal_endpoint(proposal_id: str):
    """Fetch a single proposal by its ID."""
    doc = _get_proposal(proposal_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return doc


# ─────────────────────────────────────────────────────────────────────
# Audit Verdict  (Agent 3)
# ─────────────────────────────────────────────────────────────────────

@router.post("/audit/verdict")
async def submit_verdict(verdict: AuditVerdict):
    """Agent 3 submits its audit verdict.  Triggers auto-execute or HITL.
    Updates the aegis-proposals document in place.
    """
    proposal = await run_in_threadpool(_get_proposal, verdict.proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if verdict.requires_hitl:
        sent = await send_hitl_approval_request(
            proposal_id=verdict.proposal_id,
            threat_headline=proposal.get("rationale", "Supply chain threat"),
            original_supplier=proposal["original_supplier_id"],
            proposed_supplier=proposal["proposed_supplier_name"],
            reroute_cost=verdict.cost_usd,
            attention_score=proposal["attention_score"],
            drive_time_min=proposal["mapbox_drive_time_minutes"],
            rationale=verdict.explanation,
        )
        await run_in_threadpool(_update_proposal, verdict.proposal_id, {
            "hitl_status":     "awaiting_approval",
            "hitl_slack_sent": sent,
            "requires_hitl":   True,
            "confidence":      verdict.confidence,
            "audit_explanation": verdict.explanation,
        })
        return {
            "status":  "hitl_pending",
            "slack_sent": sent,
            "message": f"Cost ${verdict.cost_usd:,.2f} exceeds threshold. "
                       "Slack approval requested.",
        }

    # Auto-execute — cost within threshold
    await run_in_threadpool(_update_proposal, verdict.proposal_id, {
        "hitl_status":     "auto_approved",
        "approved":        True,
        "requires_hitl":   False,
        "confidence":      verdict.confidence,
        "rl_adjustment":   verdict.rl_adjustment,
        "audit_explanation": verdict.explanation,
    })

    if verdict.rl_adjustment != 0:
        await run_in_threadpool(
            _apply_rl_adjustment,
            proposal["original_supplier_id"], 
            -abs(verdict.rl_adjustment)
        )

    return {
        "status":  "auto_executed",
        "message": f"Cost ${verdict.cost_usd:,.2f} within threshold. Reroute auto-approved.",
    }


# ─────────────────────────────────────────────────────────────────────
# Slack HITL Callback
# ─────────────────────────────────────────────────────────────────────

@slack_router.post("/slack/actions")
async def slack_action_callback(request: Request):
    """Handles Slack interactive button callbacks (Approve / Reject)."""
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not timestamp:
        raise HTTPException(status_code=403, detail="Missing X-Slack-Request-Timestamp header")

    if settings.slack_signing_secret and not verify_slack_signature(
        timestamp, body, signature
    ):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    actions = payload.get("actions", [])
    if not actions:
        raise HTTPException(status_code=400, detail="No actions in payload")

    action    = actions[0]
    proposal_id = action.get("value", "")
    action_id   = action.get("action_id", "")
    user        = payload.get("user", {})

    proposal = await run_in_threadpool(_get_proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if action_id == "hitl_approve":
        await run_in_threadpool(_update_proposal, proposal_id, {
            "hitl_status": "approved",
            "approved":    True,
            "approved_by": user.get("username", "unknown"),
        })
        logger.info("Proposal %s APPROVED by %s", proposal_id, user.get("username"))
        return {"response_type": "in_channel", "text": f"Reroute `{proposal_id}` APPROVED."}

    if action_id == "hitl_reject":
        await run_in_threadpool(_update_proposal, proposal_id, {
            "hitl_status": "rejected",
            "approved":    False,
            "rejected_by": user.get("username", "unknown"),
        })
        logger.info("Proposal %s REJECTED by %s", proposal_id, user.get("username"))
        # Penalise the proposed supplier that was rejected
        await run_in_threadpool(
            _apply_rl_adjustment,
            proposal["proposed_supplier_id"], 
            -settings.rl_penalty_factor
        )
        return {"response_type": "in_channel", "text": f"Reroute `{proposal_id}` REJECTED."}

    raise HTTPException(status_code=400, detail=f"Unknown action: {action_id}")


# ─────────────────────────────────────────────────────────────────────
# Reinforcement Learning Weight Updates
# ─────────────────────────────────────────────────────────────────────

@router.post("/rl/update")
def rl_update(update: RLUpdate):
    """Feedback loop: update supplier reliability based on delivery outcome."""
    es = get_es_client()

    search_resp = es.search(
        index="erp-locations",
        body={"query": {"term": {"location_id": update.supplier_id}}, "size": 1},
    )
    hits = search_resp["hits"]["hits"]
    if not hits:
        raise HTTPException(status_code=404, detail="Supplier not found")

    current_ri = hits[0]["_source"].get("reliability_index", 0.5)

    if update.outcome == "success":
        delta = settings.rl_reward_factor
    else:
        delay_factor = min(update.delivery_delay_hours / 24.0, 3.0)
        delta = -settings.rl_penalty_factor * (1 + delay_factor)

    new_ri = max(0.0, min(1.0, current_ri + delta))
    update_reliability_index(update.supplier_id, new_ri)

    return {
        "supplier_id":          update.supplier_id,
        "previous_reliability": round(current_ri, 4),
        "new_reliability":      round(new_ri, 4),
        "delta":                round(delta, 4),
    }


def _apply_rl_adjustment(supplier_id: str, delta: float) -> None:
    """Internal helper: adjust a supplier's reliability_index by delta."""
    es = get_es_client()
    try:
        resp = es.search(
            index="erp-locations",
            body={"query": {"term": {"location_id": supplier_id}}, "size": 1},
        )
        hits = resp["hits"]["hits"]
        if hits:
            current = hits[0]["_source"].get("reliability_index", 0.5)
            new_val = max(0.0, min(1.0, current + delta))
            update_reliability_index(supplier_id, new_val)
    except Exception as exc:
        logger.error("RL adjustment failed for %s: %s", supplier_id, exc)


# ─────────────────────────────────────────────────────────────────────
# Dashboard State  (consumed by Next.js frontend)
# ─────────────────────────────────────────────────────────────────────

@router.get("/dashboard/state", response_model=DashboardState)
async def dashboard_state():
    """Aggregate current system state for the frontend globe view."""
    es = get_es_client()

    try:
        # Active weather threats
        threats_resp = await run_in_threadpool(
            es.search,
            index="weather-threats",
            body={
                "size": 200,
                "query": {"term": {"status": "active"}},
                "sort": [{"ingested_at": "desc"}],
            },
        )
        active_threats = [h["_source"] for h in threats_resp["hits"]["hits"]]

        # ERP locations
        locs_resp = await run_in_threadpool(
            es.search,
            index="erp-locations",
            body={"size": 500, "query": {"term": {"active": True}}},
        )
        erp_locations = [h["_source"] for h in locs_resp["hits"]["hits"]]

        # Value at risk — sum inventory in threat zones
        value_at_risk = 0.0
        
        valid_zones = [
            t["affected_zone"] for t in active_threats 
            if t.get("affected_zone")
        ]
        
        if valid_zones:
            msearch_body = []
            for zone in valid_zones:
                msearch_body.extend([
                    {"index": "erp-locations"},
                    {
                        "size": 0,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"geo_shape": {
                                        "coordinates": {
                                            "shape": zone,
                                            "relation": "intersects"
                                        }
                                    }},
                                    {"term": {"active": True}}
                                ]
                            }
                        },
                        "aggs": {"total_value": {"sum": {"field": "inventory_value_usd"}}}
                    }
                ])
                
            msearch_resp = await run_in_threadpool(es.msearch, body=msearch_body)
            
            for resp in msearch_resp.get("responses", []):
                if not resp.get("error"):
                    value_at_risk += (
                        resp.get("aggregations", {})
                            .get("total_value", {})
                            .get("value", 0)
                    )

        # Active routes — proposals that are visible on the map
        active_routes, _ = await run_in_threadpool(
            _list_proposals,
            statuses=["auto_approved", "approved", "awaiting_approval"],
            size=200,
            sort_by="created_at",
            sort_order="desc",
        )

        # Pending — proposals awaiting human decision
        pending, _ = await run_in_threadpool(
            _list_proposals,
            statuses=["pending", "awaiting_approval"],
            size=100,
            sort_by="created_at",
            sort_order="desc",
        )

        return DashboardState(
            active_threats=active_threats,
            erp_locations=erp_locations,
            active_routes=active_routes,
            pending_proposals=pending,
            total_value_at_risk=value_at_risk,
        )
    except Exception as exc:
        logger.error("Failed to aggregate dashboard state (Elasticsearch offline?): %s", exc)
        return DashboardState(
            active_threats=[],
            erp_locations=[],
            active_routes=[],
            pending_proposals=[],
            total_value_at_risk=0.0,
        )


# ─────────────────────────────────────────────────────────────────────
# Chat-to-Map — Conversational explainability
# ─────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat_to_map(query: ChatQuery):
    """Answer operator questions about agent decisions with ES|QL rationale.

    Flow
    ----
    1. Claude Haiku classifies the question into one of four intents
       (supplier_ranking | risk_assessment | reroute_status | general).
    2. The matching ES|QL query from the catalog is executed against Elasticsearch.
    3. Claude Sonnet synthesises the live results into a natural-language explanation.
    4. The exact ES|QL query is returned for auditability.
    """
    es = get_es_client()
    intent = await classify_intent(query.question)
    logger.info("Chat intent=%s question=%r", intent, query.question[:80])

    # ── INTENT: supplier_ranking ──────────────────────────────────────────────
    if intent == "supplier_ranking":
        esql_query = ESQL_SUPPLIER_RANKING
        try:
            def _query_ranking():
                res = es.esql.query(query=esql_query)
                cols = [col.name for col in res.columns]
                return [dict(zip(cols, row)) for row in res.values]
            table = await run_in_threadpool(_query_ranking)
        except Exception as exc:
            logger.warning(
                "LOOKUP JOIN failed (supplier-sla-scores not populated?): %s. "
                "Falling back to reliability-only ranking.", exc,
            )
            esql_query = ESQL_SUPPLIER_RANKING_FALLBACK
            def _query_fallback():
                res = es.esql.query(query=esql_query)
                cols = [col.name for col in res.columns]
                return [dict(zip(cols, row)) for row in res.values]
            table = await run_in_threadpool(_query_fallback)

        answer = await explain_results(
            question=query.question,
            esql_query=esql_query,
            table=table,
            context_threat_id=query.context_threat_id,
        )
        return ChatResponse(
            answer=answer,
            esql_query=esql_query,
            highlighted_entities=[r.get("name", "") for r in table[:3]],
            map_annotations=[
                {"type": "highlight_supplier", "supplier_id": r.get("location_id")}
                for r in table[:5]
            ],
        )

    # ── INTENT: risk_assessment ───────────────────────────────────────────────
    if intent == "risk_assessment":
        esql_query = ESQL_RISK_ASSESSMENT
        try:
            def _query_risk():
                res = es.esql.query(query=esql_query)
                cols = [col.name for col in res.columns]
                return [dict(zip(cols, row)) for row in res.values]
            table = await run_in_threadpool(_query_risk)
        except Exception as exc:
            logger.warning("Risk assessment query failed: %s", exc)
            table = []

        answer = await explain_results(
            question=query.question,
            esql_query=esql_query,
            table=table,
            context_threat_id=query.context_threat_id,
        )
        return ChatResponse(
            answer=answer,
            esql_query=esql_query,
            highlighted_entities=[r.get("event_type", "") for r in table],
        )

    # ── INTENT: reroute_status ────────────────────────────────────────────────
    if intent == "reroute_status":
        approved, _ = await run_in_threadpool(
            _list_proposals,
            statuses=["approved", "auto_approved"],
            size=5,
            sort_by="created_at",
            sort_order="desc",
        )
        table = approved or []

        answer = await explain_results(
            question=query.question,
            esql_query=ESQL_REROUTE_PROPOSALS,
            table=table,
            context_threat_id=query.context_threat_id,
        )

        highlighted: list[str] = []
        annotations: list[dict[str, Any]] = []
        if table:
            latest = table[0]
            highlighted = [
                latest.get("original_supplier_id", ""),
                latest.get("proposed_supplier_id", ""),
            ]
            annotations = [{"type": "route", "proposal_id": latest.get("proposal_id")}]

        return ChatResponse(
            answer=answer,
            esql_query=ESQL_REROUTE_PROPOSALS,
            highlighted_entities=highlighted,
            map_annotations=annotations,
        )

    # ── INTENT: general (fallthrough) ─────────────────────────────────────────
    return ChatResponse(
        answer=(
            "I can help with questions about: supplier selection rationale, "
            "current risk assessment, or active reroutes. Try asking "
            "'Why did you choose Vendor C?' or 'What is the current value at risk?'"
        )
    )


# ─────────────────────────────────────────────────────────────────────
# Chat-to-Map Streaming — real-time chain-of-thought via SSE
# ─────────────────────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_to_map_stream(query: ChatQuery):
    """Stream agent explanations token-by-token via Server-Sent Events.

    SSE event types emitted:
        metadata  — esql_query, highlighted_entities, map_annotations (once)
        token     — text delta from Claude (many)
        done      — stream complete (once)
        error     — on failure (once, optional)

    The client should accumulate all ``token`` payloads to reconstruct the
    full answer text.
    """
    es = get_es_client()
    intent = await classify_intent(query.question)
    logger.info("Chat stream intent=%s question=%r", intent, query.question[:80])

    # Resolve ES|QL query and metadata (same logic as /chat)
    esql_query: str = ""
    table: list[dict[str, Any]] = []
    highlighted_entities: list[str] = []
    map_annotations: list[dict[str, Any]] = []

    if intent == "supplier_ranking":
        esql_query = ESQL_SUPPLIER_RANKING
        try:
            def _query_ranking():
                res = es.esql.query(query=esql_query)
                cols = [col.name for col in res.columns]
                return [dict(zip(cols, row)) for row in res.values]
            table = await run_in_threadpool(_query_ranking)
        except Exception:
            esql_query = ESQL_SUPPLIER_RANKING_FALLBACK
            def _query_fallback():
                res = es.esql.query(query=esql_query)
                cols = [col.name for col in res.columns]
                return [dict(zip(cols, row)) for row in res.values]
            table = await run_in_threadpool(_query_fallback)
        highlighted_entities = [r.get("name", "") for r in table[:3]]
        map_annotations = [
            {"type": "highlight_supplier", "supplier_id": r.get("location_id")}
            for r in table[:5]
        ]

    elif intent == "risk_assessment":
        esql_query = ESQL_RISK_ASSESSMENT
        try:
            def _query_risk():
                res = es.esql.query(query=esql_query)
                cols = [col.name for col in res.columns]
                return [dict(zip(cols, row)) for row in res.values]
            table = await run_in_threadpool(_query_risk)
        except Exception:
            table = []
        highlighted_entities = [r.get("event_type", "") for r in table]

    elif intent == "reroute_status":
        esql_query = ESQL_REROUTE_PROPOSALS
        approved, _ = await run_in_threadpool(
            _list_proposals,
            statuses=["approved", "auto_approved"],
            size=5,
            sort_by="created_at",
            sort_order="desc",
        )
        table = approved or []
        if table:
            latest = table[0]
            highlighted_entities = [
                latest.get("original_supplier_id", ""),
                latest.get("proposed_supplier_id", ""),
            ]
            map_annotations = [{"type": "route", "proposal_id": latest.get("proposal_id")}]

    else:
        # general intent — no query, no streaming needed
        async def _general_stream():
            msg = (
                "I can help with questions about: supplier selection rationale, "
                "current risk assessment, or active reroutes. Try asking "
                "'Why did you choose Vendor C?' or 'What is the current value at risk?'"
            )
            yield f"event: metadata\ndata: {json.dumps({'esql_query': None, 'highlighted_entities': [], 'map_annotations': []})}\n\n"
            yield f"event: token\ndata: {json.dumps({'text': msg})}\n\n"
            yield "event: done\ndata: {}\n\n"
        return StreamingResponse(
            _general_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    # Build SSE generator
    async def _stream():
        # Emit metadata first so the UI can show ES|QL toggle + highlights immediately
        meta = {
            "esql_query": esql_query,
            "highlighted_entities": highlighted_entities,
            "map_annotations": map_annotations,
        }
        yield f"event: metadata\ndata: {json.dumps(meta, default=str)}\n\n"

        # Stream tokens from Claude
        try:
            async for token in stream_explanation(
                question=query.question,
                esql_query=esql_query,
                table=table,
                context_threat_id=query.context_threat_id,
            ):
                yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"
        except Exception as exc:
            logger.error("Chat stream error: %s", exc)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Server-Sent Events — real-time push to all browser sessions
# ─────────────────────────────────────────────────────────────────────

@router.get("/events")
async def sse_events(request: Request):
    """Server-Sent Events stream for real-time dashboard updates.

    The browser opens one long-lived GET /events connection per tab.
    When the backend broadcasts (pipeline_complete, execution_event,
    ingest_complete), every connected tab receives it instantly and
    re-fetches /dashboard/state to refresh the globe.

    SSE event names
    ---------------
    connected          — initial handshake (no action needed)
    execution_event    — Elastic Workflow executed a reroute
    pipeline_complete  — 3-agent pipeline finished a cycle
    ingest_complete    — NOAA/FIRMS poll completed

    Browser usage::

        const es = new EventSource('/events');
        es.addEventListener('pipeline_complete', () => reloadState());
        es.addEventListener('execution_event',   () => reloadState());
    """
    from app.core.events import subscribe, unsubscribe

    async def _stream():
        q = await subscribe()
        try:
            # Immediate handshake so the client knows the connection is live
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    envelope = await asyncio.wait_for(q.get(), timeout=15.0)
                    event_type = envelope.get("type", "message")
                    data       = json.dumps(envelope.get("data", {}))
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # SSE keepalive comment — prevents proxies/load-balancers
                    # from closing the idle connection
                    yield ": ping\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # tell nginx not to buffer SSE
            "Connection":       "keep-alive",
        },
    )
