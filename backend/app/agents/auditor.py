"""Agent 3 — Auditor Agent.

Implements the Reflection Pattern with Reinforcement Learning.
Evaluates proposals from Agent 2, enforces dynamic confidence
thresholds, and triggers HITL escalation or auto-execution via
Elastic Workflows.

Dynamic Confidence Threshold:
  - Cost < $50,000  → auto-execute (Elastic Workflow: auto-execute)
  - Cost >= $50,000 → HITL Slack approval (Elastic Workflow: slack-approval)

RL Loop:
  - Penalizes reliability_index of historically poor vendors.
  - Rewards vendors that deliver on time after reroute.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.elastic import get_es_client
from app.services.indexer import update_reliability_index

logger = logging.getLogger("aegis.agent.auditor")

# Reflection criteria weights
REFLECTION_WEIGHTS = {
    "attention_score": 0.30,
    "reliability": 0.25,
    "cost_efficiency": 0.20,
    "drive_time_penalty": 0.15,
    "sla_compliance": 0.10,
}


async def evaluate_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Run the Auditor Reflection Pattern on a single reroute proposal.

    Returns an audit verdict with approval/rejection, confidence score,
    HITL determination, and RL adjustments.
    """
    es = get_es_client()

    attention = proposal.get("attention_score", 0)
    reliability = proposal.get("reliability_index", 0.5)
    cost = proposal.get("reroute_cost_usd", 0)
    drive_time = proposal.get("mapbox_drive_time_minutes", 999)
    sla_match = proposal.get("vector_similarity", proposal.get("sla_match_score", 0.5))

    # ── Reflection Step 1: Score each dimension ──────────────────────
    # Normalize drive time (lower is better, cap at 600 min)
    drive_time_norm = max(0, 1 - (drive_time / 600.0))

    # Cost efficiency (lower cost = higher score, normalize against threshold)
    cost_norm = max(0, 1 - (cost / (settings.hitl_cost_threshold_usd * 2)))

    # Composite confidence score
    confidence = (
        REFLECTION_WEIGHTS["attention_score"] * min(attention * 10, 1.0)
        + REFLECTION_WEIGHTS["reliability"] * reliability
        + REFLECTION_WEIGHTS["cost_efficiency"] * cost_norm
        + REFLECTION_WEIGHTS["drive_time_penalty"] * drive_time_norm
        + REFLECTION_WEIGHTS["sla_compliance"] * sla_match
    )
    confidence = round(max(0.0, min(1.0, confidence)), 4)

    # ── Reflection Step 2: Historical vendor check ───────────────────
    proposed_id = proposal.get("proposed_supplier_id", "")
    historical_penalty = 0.0

    try:
        hist_resp = es.search(
            index="supply-latency-logs",
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"supplier_id": proposed_id}},
                            {"range": {"@timestamp": {"gte": "now-90d"}}},
                        ]
                    }
                },
                "aggs": {
                    "avg_delay": {"avg": {"field": "delay_hours"}},
                    "late_pct": {
                        "filter": {"term": {"on_time": False}},
                    },
                    "total": {"value_count": {"field": "on_time"}},
                },
            },
        )
        aggs = hist_resp.get("aggregations", {})
        avg_delay = aggs.get("avg_delay", {}).get("value", 0) or 0
        late_count = aggs.get("late_pct", {}).get("doc_count", 0)
        total_count = aggs.get("total", {}).get("value", 1) or 1
        late_ratio = late_count / total_count

        # Apply penalty if vendor has >30% late deliveries or avg delay >4h
        if late_ratio > 0.3 or avg_delay > 4.0:
            historical_penalty = settings.rl_penalty_factor * (1 + late_ratio)
            confidence -= historical_penalty * 0.5  # reduce confidence
            confidence = max(0.0, confidence)
            logger.info(
                "Historical penalty for %s: late_ratio=%.2f, avg_delay=%.1fh, penalty=%.4f",
                proposed_id, late_ratio, avg_delay, historical_penalty,
            )
    except Exception as exc:
        logger.warning("Historical check failed for %s: %s", proposed_id, exc)

    # ── Reflection Step 3: Dynamic threshold decision ────────────────
    requires_hitl = cost >= settings.hitl_cost_threshold_usd

    # Additional HITL trigger: low confidence on expensive reroutes
    if confidence < 0.4 and cost > settings.hitl_cost_threshold_usd * 0.5:
        requires_hitl = True

    # Determine approval for auto-execute path
    approved = not requires_hitl and confidence >= 0.3

    # ── Reflection Step 4: RL adjustment recommendation ──────────────
    rl_adjustment = 0.0
    if historical_penalty > 0:
        rl_adjustment = -historical_penalty
        # Actually apply the RL penalty to the original failing supplier
        original_id = proposal.get("original_supplier_id", "")
        if original_id:
            try:
                orig_resp = es.search(
                    index="erp-locations",
                    body={
                        "query": {"term": {"location_id": original_id}},
                        "size": 1,
                        "_source": ["reliability_index"],
                    },
                )
                hits = orig_resp["hits"]["hits"]
                if hits:
                    current_ri = hits[0]["_source"].get("reliability_index", 0.5)
                    new_ri = max(0.0, current_ri - abs(historical_penalty))
                    update_reliability_index(original_id, new_ri)
                    logger.info(
                        "RL penalty applied to %s: %.4f → %.4f",
                        original_id, current_ri, new_ri,
                    )
            except Exception as exc:
                logger.error("RL update failed for %s: %s", original_id, exc)

    # Build explanation
    explanation_parts = [
        f"Confidence: {confidence:.4f}.",
        f"Attention score contribution: {attention:.6f}.",
        f"Reliability: {reliability:.3f}, SLA match: {sla_match:.3f}.",
        f"Drive time: {drive_time:.0f} min, Cost: ${cost:,.2f}.",
    ]
    if historical_penalty > 0:
        explanation_parts.append(
            f"Historical penalty applied: {historical_penalty:.4f} "
            f"(vendor had poor delivery history)."
        )
    if requires_hitl:
        explanation_parts.append(
            f"HITL required: cost ${cost:,.2f} exceeds "
            f"${settings.hitl_cost_threshold_usd:,.0f} threshold."
        )
    else:
        explanation_parts.append("Auto-execution approved: within cost threshold.")

    verdict = {
        "proposal_id": proposal["proposal_id"],
        "approved": approved,
        "confidence": confidence,
        "cost_usd": cost,
        "requires_hitl": requires_hitl,
        "hitl_status": "pending" if requires_hitl else ("auto_approved" if approved else "rejected"),
        "rl_adjustment": round(rl_adjustment, 4),
        "explanation": " ".join(explanation_parts),
        "reflection_scores": {
            "attention_weighted": round(min(attention * 10, 1.0) * REFLECTION_WEIGHTS["attention_score"], 4),
            "reliability_weighted": round(reliability * REFLECTION_WEIGHTS["reliability"], 4),
            "cost_efficiency_weighted": round(cost_norm * REFLECTION_WEIGHTS["cost_efficiency"], 4),
            "drive_time_weighted": round(drive_time_norm * REFLECTION_WEIGHTS["drive_time_penalty"], 4),
            "sla_weighted": round(sla_match * REFLECTION_WEIGHTS["sla_compliance"], 4),
            "historical_penalty": round(historical_penalty, 4),
        },
    }

    logger.info(
        "Auditor verdict for %s: approved=%s, confidence=%.4f, hitl=%s",
        proposal["proposal_id"], approved, confidence, requires_hitl,
    )

    return verdict


async def run_auditor_cycle(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate all proposals from Agent 2 and return verdicts."""
    verdicts = []
    for proposal in proposals:
        verdict = await evaluate_proposal(proposal)
        verdicts.append(verdict)
    return verdicts
