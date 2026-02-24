"""Agent Orchestrator — Multi-Agent Reflection Pipeline.

Coordinates the three-agent pipeline:
  Agent 1 (Watcher)     → Detect threats & predict bottlenecks
  Agent 2 (Procurement) → Score suppliers & propose reroutes
  Agent 3 (Auditor)     → Reflect, apply RL, enforce HITL thresholds

Runs as a scheduled background task or can be triggered manually.
All proposals and verdict outcomes are persisted to the aegis-proposals
Elasticsearch index so they survive restarts and are queryable in Kibana.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.watcher import run_watcher_cycle
from app.agents.procurement import run_procurement_cycle
from app.agents.auditor import run_auditor_cycle
from app.services.slack import send_hitl_approval_request
from app.services.proposals import (
    upsert_proposal,
    update_proposal as _update_proposal,
)
from app.core.config import settings

logger = logging.getLogger("aegis.orchestrator")

# Callable that the WebSocket endpoint injects to stream progress events.
EmitFn = Callable[[dict[str, Any]], Awaitable[None]] | None


async def run_full_pipeline(emit: EmitFn = None) -> dict[str, Any]:
    """Execute the complete three-agent reflection pipeline.

    Args:
        emit: Optional async callable invoked after each agent completes.
              Signature: ``await emit({"agent": str, "status": str, ...})``.
              Used by the /ws/pipeline WebSocket endpoint to stream progress.
    """

    async def _emit(event: dict[str, Any]) -> None:
        if emit:
            try:
                await emit(event)
            except Exception as exc:
                logger.debug("Pipeline emit error (client gone?): %s", exc)

    pipeline_result: dict[str, Any] = {
        "watcher": {},
        "procurement": [],
        "auditor": [],
        "actions_taken": [],
    }

    # ── Agent 1: Watcher ─────────────────────────────────────────────
    logger.info("=== Pipeline: Running Agent 1 (Watcher) ===")
    await _emit({"agent": "watcher", "status": "running"})

    watcher_result = await run_watcher_cycle()
    pipeline_result["watcher"] = {
        "bottleneck_count":    len(watcher_result.get("bottleneck_predictions", [])),
        "at_risk_locations":   len(watcher_result.get("at_risk_locations", [])),
        "total_value_at_risk": watcher_result.get("total_value_at_risk", 0),
        "threat_correlations": len(watcher_result.get("threat_correlations", [])),
    }
    await _emit({
        "agent":       "watcher",
        "status":      "complete",
        "threats":     len(watcher_result.get("threat_correlations", [])),
        "at_risk":     len(watcher_result.get("at_risk_locations", [])),
        "bottlenecks": len(watcher_result.get("bottleneck_predictions", [])),
        "var_usd":     watcher_result.get("total_value_at_risk", 0),
    })

    correlations = watcher_result.get("threat_correlations", [])
    if not correlations:
        logger.info("No threat correlations found. Pipeline complete (no action needed).")
        await _emit({"agent": "pipeline", "status": "complete", "actions": 0,
                     "reason": "no_correlations"})
        return pipeline_result

    # ── Agent 2: Procurement — for each threat correlation ───────────
    logger.info("=== Pipeline: Running Agent 2 (Procurement) ===")
    await _emit({"agent": "procurement", "status": "running",
                 "correlations": len(correlations)})
    all_proposals: list[dict[str, Any]] = []

    for corr in correlations:
        threat_id    = corr["threat_id"]
        affected_locs = corr.get("affected_locations", [])
        if not affected_locs:
            continue

        # Use the highest-value affected location as the origin
        origin = max(affected_locs, key=lambda x: x.get("inventory_value_usd", 0))

        from app.core.elastic import get_es_client
        es = get_es_client()

        origin_resp = es.search(
            index="erp-locations",
            body={"query": {"term": {"location_id": origin["location_id"]}}, "size": 1},
        )
        origin_hits = origin_resp["hits"]["hits"]
        if not origin_hits:
            continue
        origin_doc = origin_hits[0]["_source"]

        threat_resp = es.search(
            index="weather-threats",
            body={"query": {"term": {"threat_id": threat_id}}, "size": 1},
        )
        threat_hits = threat_resp["hits"]["hits"]
        if not threat_hits:
            continue
        threat_doc = threat_hits[0]["_source"]

        proposals = await run_procurement_cycle(
            threat_id=threat_id,
            threat_centroid=threat_doc.get("centroid", {"lat": 0, "lon": 0}),
            affected_zone=threat_doc.get("affected_zone", {}),
            origin_location=origin_doc,
        )

        # ── Persist each proposal immediately ────────────────────────
        for p in proposals:
            try:
                upsert_proposal({**p, "hitl_status": "pending"})
            except Exception as exc:
                logger.error("Failed to persist proposal %s: %s", p.get("proposal_id"), exc)

        all_proposals.extend(proposals)

    pipeline_result["procurement"] = [
        {
            "proposal_id":    p["proposal_id"],
            "threat_id":      p["threat_id"],
            "supplier":       p["proposed_supplier_name"],
            "attention_score": p["attention_score"],
            "cost":           p["reroute_cost_usd"],
        }
        for p in all_proposals
    ]

    await _emit({"agent": "procurement", "status": "complete",
                 "proposals": len(all_proposals)})

    if not all_proposals:
        logger.info("No reroute proposals generated. Pipeline complete.")
        await _emit({"agent": "pipeline", "status": "complete", "actions": 0,
                     "reason": "no_proposals"})
        return pipeline_result

    # ── Agent 3: Auditor — reflect on best proposal per threat ───────
    logger.info("=== Pipeline: Running Agent 3 (Auditor) ===")
    await _emit({"agent": "auditor", "status": "running",
                 "proposals": len(all_proposals)})

    best_per_threat: dict[str, dict] = {}
    for p in all_proposals:
        tid = p["threat_id"]
        if tid not in best_per_threat or p["attention_score"] > best_per_threat[tid]["attention_score"]:
            best_per_threat[tid] = p

    verdicts = await run_auditor_cycle(list(best_per_threat.values()))
    pipeline_result["auditor"] = verdicts

    # ── Execute actions and persist verdict outcomes ──────────────────
    for verdict in verdicts:
        proposal_id = verdict["proposal_id"]

        # Find the full proposal from our in-memory list (avoids an ES round-trip)
        proposal = next(
            (p for p in all_proposals if p["proposal_id"] == proposal_id), {}
        )

        if verdict["requires_hitl"]:
            sent = await send_hitl_approval_request(
                proposal_id=proposal_id,
                threat_headline=proposal.get("rationale", "Reroute required"),
                original_supplier=proposal.get("original_supplier_id", ""),
                proposed_supplier=proposal.get("proposed_supplier_name", ""),
                reroute_cost=verdict["cost_usd"],
                attention_score=proposal.get("attention_score", 0),
                drive_time_min=proposal.get("mapbox_drive_time_minutes", 0),
                rationale=verdict["explanation"],
            )
            _persist_verdict(proposal_id, verdict, hitl_status="awaiting_approval",
                             extra={"hitl_slack_sent": sent})
            pipeline_result["actions_taken"].append({
                "type":        "hitl_slack_approval",
                "proposal_id": proposal_id,
                "slack_sent":  sent,
            })

        elif verdict["approved"]:
            _persist_verdict(proposal_id, verdict, hitl_status="auto_approved",
                             extra={"approved": True})
            pipeline_result["actions_taken"].append({
                "type":        "auto_executed",
                "proposal_id": proposal_id,
                "confidence":  verdict["confidence"],
            })

        else:
            _persist_verdict(proposal_id, verdict, hitl_status="rejected",
                             extra={"approved": False})
            pipeline_result["actions_taken"].append({
                "type":        "rejected",
                "proposal_id": proposal_id,
                "confidence":  verdict["confidence"],
                "reason":      verdict["explanation"],
            })

    actions = pipeline_result["actions_taken"]
    await _emit({
        "agent":    "auditor",
        "status":   "complete",
        "approved": sum(1 for a in actions if a["type"] == "auto_executed"),
        "hitl":     sum(1 for a in actions if a["type"] == "hitl_slack_approval"),
        "rejected": sum(1 for a in actions if a["type"] == "rejected"),
    })
    await _emit({
        "agent":   "pipeline",
        "status":  "complete",
        "actions": len(actions),
    })

    logger.info(
        "Pipeline complete. Proposals: %d, Verdicts: %d, Actions: %d",
        len(all_proposals),
        len(verdicts),
        len(actions),
    )
    return pipeline_result


# ── Helper ────────────────────────────────────────────────────────────────────

def _persist_verdict(
    proposal_id: str,
    verdict: dict[str, Any],
    hitl_status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write verdict fields back to the aegis-proposals document."""
    fields: dict[str, Any] = {
        "hitl_status":       hitl_status,
        "requires_hitl":     verdict.get("requires_hitl", False),
        "confidence":        verdict.get("confidence", 0.0),
        "rl_adjustment":     verdict.get("rl_adjustment", 0.0),
        "audit_explanation": verdict.get("explanation", ""),
    }
    if extra:
        fields.update(extra)
    try:
        _update_proposal(proposal_id, fields)
    except Exception as exc:
        logger.error("Failed to persist verdict for %s: %s", proposal_id, exc)
