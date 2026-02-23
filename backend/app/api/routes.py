"""Core API routes — Mapbox routing, Slack HITL, RL updates, dashboard state, chat."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.elastic import get_es_client
from app.models.schemas import (
    AuditVerdict,
    ChatQuery,
    ChatResponse,
    DashboardState,
    MapboxRouteRequest,
    MapboxRouteResponse,
    RerouteProposal,
    RLUpdate,
    SlackAction,
)
from app.services.mapbox import get_route
from app.services.slack import send_hitl_approval_request, verify_slack_signature
from app.services.indexer import update_reliability_index

logger = logging.getLogger("aegis.api.routes")
router = APIRouter(tags=["core"])

# ── In-memory proposal store (production: use Elasticsearch index) ────
_proposals: dict[str, dict[str, Any]] = {}


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
# Reroute Proposals (Agent 2 → Agent 3 pipeline)
# ─────────────────────────────────────────────────────────────────────
@router.post("/proposals")
async def submit_proposal(proposal: RerouteProposal):
    """Agent 2 submits a reroute proposal for Agent 3 review."""
    _proposals[proposal.proposal_id] = proposal.model_dump()
    logger.info("Proposal %s submitted", proposal.proposal_id)
    return {"status": "received", "proposal_id": proposal.proposal_id}


@router.get("/proposals")
async def list_proposals():
    return list(_proposals.values())


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str):
    if proposal_id not in _proposals:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _proposals[proposal_id]


# ─────────────────────────────────────────────────────────────────────
# Audit Verdict (Agent 3)
# ─────────────────────────────────────────────────────────────────────
@router.post("/audit/verdict")
async def submit_verdict(verdict: AuditVerdict):
    """Agent 3 submits its audit verdict. Triggers auto-execute or HITL."""
    if verdict.proposal_id not in _proposals:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = _proposals[verdict.proposal_id]

    if verdict.requires_hitl:
        # Cost exceeds threshold — send Slack approval request
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
        proposal["hitl_status"] = "awaiting_approval"
        proposal["hitl_slack_sent"] = sent
        return {
            "status": "hitl_pending",
            "slack_sent": sent,
            "message": f"Cost ${verdict.cost_usd:,.2f} exceeds threshold. Slack approval requested.",
        }
    else:
        # Auto-execute — cost is within threshold
        proposal["hitl_status"] = "auto_approved"
        proposal["approved"] = True

        # Apply RL adjustment if specified
        if verdict.rl_adjustment != 0:
            _apply_rl_adjustment(
                proposal["original_supplier_id"], -abs(verdict.rl_adjustment)
            )

        return {
            "status": "auto_executed",
            "message": f"Cost ${verdict.cost_usd:,.2f} within threshold. Reroute auto-approved.",
        }


# ─────────────────────────────────────────────────────────────────────
# Slack HITL Callback
# ─────────────────────────────────────────────────────────────────────
@router.post("/slack/actions")
async def slack_action_callback(request: Request):
    """Handles Slack interactive button callbacks (Approve/Reject)."""
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if settings.slack_signing_secret and not verify_slack_signature(
        timestamp, body, signature
    ):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    actions = payload.get("actions", [])
    if not actions:
        raise HTTPException(status_code=400, detail="No actions in payload")

    action = actions[0]
    proposal_id = action.get("value", "")
    action_id = action.get("action_id", "")
    user = payload.get("user", {})

    if proposal_id not in _proposals:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = _proposals[proposal_id]

    if action_id == "hitl_approve":
        proposal["hitl_status"] = "approved"
        proposal["approved"] = True
        proposal["approved_by"] = user.get("username", "unknown")
        logger.info("Proposal %s APPROVED by %s", proposal_id, user.get("username"))

        return {"response_type": "in_channel", "text": f"Reroute `{proposal_id}` APPROVED."}

    elif action_id == "hitl_reject":
        proposal["hitl_status"] = "rejected"
        proposal["approved"] = False
        proposal["rejected_by"] = user.get("username", "unknown")
        logger.info("Proposal %s REJECTED by %s", proposal_id, user.get("username"))

        # Penalize the proposed supplier's reliability since it was rejected
        _apply_rl_adjustment(
            proposal["proposed_supplier_id"], -settings.rl_penalty_factor
        )

        return {"response_type": "in_channel", "text": f"Reroute `{proposal_id}` REJECTED."}

    raise HTTPException(status_code=400, detail=f"Unknown action: {action_id}")


# ─────────────────────────────────────────────────────────────────────
# Reinforcement Learning Weight Updates
# ─────────────────────────────────────────────────────────────────────
@router.post("/rl/update")
async def rl_update(update: RLUpdate):
    """Feedback loop: update supplier reliability based on delivery outcome."""
    es = get_es_client()

    # Fetch current reliability_index
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
        # Scale penalty by delay magnitude
        delay_factor = min(update.delivery_delay_hours / 24.0, 3.0)
        delta = -settings.rl_penalty_factor * (1 + delay_factor)

    new_ri = max(0.0, min(1.0, current_ri + delta))
    update_reliability_index(update.supplier_id, new_ri)

    return {
        "supplier_id": update.supplier_id,
        "previous_reliability": round(current_ri, 4),
        "new_reliability": round(new_ri, 4),
        "delta": round(delta, 4),
    }


def _apply_rl_adjustment(supplier_id: str, delta: float) -> None:
    """Internal helper to adjust a supplier's reliability index."""
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
# Dashboard State (consumed by Next.js frontend)
# ─────────────────────────────────────────────────────────────────────
@router.get("/dashboard/state", response_model=DashboardState)
async def dashboard_state():
    """Aggregate current system state for the frontend globe view."""
    es = get_es_client()

    # Active threats
    threats_resp = es.search(
        index="weather-threats",
        body={
            "size": 200,
            "query": {"term": {"status": "active"}},
            "sort": [{"ingested_at": "desc"}],
        },
    )
    active_threats = [h["_source"] for h in threats_resp["hits"]["hits"]]

    # ERP locations
    locs_resp = es.search(
        index="erp-locations",
        body={"size": 500, "query": {"term": {"active": True}}},
    )
    erp_locations = [h["_source"] for h in locs_resp["hits"]["hits"]]

    # Total value at risk — locations that intersect active threats
    # (simplified: sum all inventory in threat zones)
    value_at_risk = 0.0
    for threat in active_threats:
        zone = threat.get("affected_zone")
        if not zone:
            continue
        var_resp = es.search(
            index="erp-locations",
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"geo_shape": {
                                "coordinates": {
                                    "shape": zone,
                                    "relation": "intersects",
                                }
                            }},
                            {"term": {"active": True}},
                        ]
                    }
                },
                "aggs": {
                    "total_value": {"sum": {"field": "inventory_value_usd"}}
                },
            },
        )
        value_at_risk += (
            var_resp.get("aggregations", {})
            .get("total_value", {})
            .get("value", 0)
        )

    # Active routes (pending/approved proposals)
    active_routes = [
        p for p in _proposals.values()
        if p.get("hitl_status") in ("auto_approved", "approved", "awaiting_approval")
    ]
    pending = [
        p for p in _proposals.values()
        if p.get("hitl_status") in ("pending", "awaiting_approval")
    ]

    return DashboardState(
        active_threats=active_threats,
        erp_locations=erp_locations,
        active_routes=active_routes,
        pending_proposals=pending,
        total_value_at_risk=value_at_risk,
    )


# ─────────────────────────────────────────────────────────────────────
# Chat-to-Map — Conversational explainability
# ─────────────────────────────────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse)
async def chat_to_map(query: ChatQuery):
    """Answer operator questions about agent decisions with ES|QL rationale."""
    es = get_es_client()
    question = query.question.lower()

    # Determine which ES|QL to run based on question intent
    if "why" in question and ("vendor" in question or "supplier" in question):
        # "Why did you choose Vendor C over Vendor A?"
        esql_query = """FROM erp-locations
| WHERE type == "supplier" AND active == true
| EVAL risk_adjusted_score = reliability_index * (1.0 / (avg_lead_time_hours + 1.0))
| SORT risk_adjusted_score DESC
| LIMIT 10
| KEEP name, location_id, reliability_index, avg_lead_time_hours, risk_adjusted_score, inventory_value_usd"""

        result = es.esql.query(query=esql_query, format="json")
        rows = result.get("values", [])
        columns = [c["name"] for c in result.get("columns", [])]

        table = [dict(zip(columns, row)) for row in rows]
        highlighted = [r.get("name", "") for r in table[:3]]

        answer = _build_supplier_rationale(table, query.question)

        return ChatResponse(
            answer=answer,
            esql_query=esql_query,
            highlighted_entities=highlighted,
            map_annotations=[
                {"type": "highlight_supplier", "supplier_id": r.get("location_id")}
                for r in table[:5]
            ],
        )

    elif "risk" in question or "value" in question:
        esql_query = """FROM weather-threats
| WHERE status == "active"
| STATS threat_count = COUNT(*), avg_severity = COUNT_DISTINCT(severity) BY event_type
| SORT threat_count DESC"""

        result = es.esql.query(query=esql_query, format="json")
        rows = result.get("values", [])
        columns = [c["name"] for c in result.get("columns", [])]
        table = [dict(zip(columns, row)) for row in rows]

        return ChatResponse(
            answer=f"Currently tracking {sum(r.get('threat_count', 0) for r in table)} active threats across {len(table)} event types.",
            esql_query=esql_query,
            highlighted_entities=[r.get("event_type", "") for r in table],
        )

    elif "route" in question or "reroute" in question:
        active_proposals = [
            p for p in _proposals.values() if p.get("approved")
        ]
        if active_proposals:
            latest = active_proposals[-1]
            return ChatResponse(
                answer=(
                    f"The latest approved reroute switches from "
                    f"{latest['original_supplier_id']} to {latest['proposed_supplier_name']} "
                    f"with an attention score of {latest['attention_score']:.4f} "
                    f"and drive time of {latest['mapbox_drive_time_minutes']:.0f} minutes. "
                    f"Rationale: {latest.get('rationale', 'N/A')}"
                ),
                highlighted_entities=[
                    latest["original_supplier_id"],
                    latest["proposed_supplier_id"],
                ],
                map_annotations=[
                    {"type": "route", "proposal_id": latest["proposal_id"]}
                ],
            )
        return ChatResponse(answer="No active reroutes at this time.")

    else:
        return ChatResponse(
            answer=(
                "I can help with questions about: supplier selection rationale, "
                "current risk assessment, or active reroutes. Try asking "
                "'Why did you choose Vendor C?' or 'What is the current value at risk?'"
            )
        )


def _build_supplier_rationale(table: list[dict], question: str) -> str:
    """Build a human-readable explanation of supplier ranking."""
    if not table:
        return "No supplier data available."

    lines = ["Here's the current supplier ranking by risk-adjusted score:\n"]
    for i, row in enumerate(table[:5], 1):
        lines.append(
            f"{i}. **{row.get('name', 'Unknown')}** — "
            f"Reliability: {row.get('reliability_index', 0):.3f}, "
            f"Avg Lead Time: {row.get('avg_lead_time_hours', 0):.1f}h, "
            f"Score: {row.get('risk_adjusted_score', 0):.4f}"
        )

    if len(table) >= 2:
        top = table[0]
        second = table[1]
        lines.append(
            f"\n{top.get('name')} ranks highest because its reliability index "
            f"({top.get('reliability_index', 0):.3f}) combined with faster lead time "
            f"({top.get('avg_lead_time_hours', 0):.1f}h) produces a superior "
            f"risk-adjusted score compared to {second.get('name')} "
            f"({second.get('risk_adjusted_score', 0):.4f})."
        )

    return "\n".join(lines)
