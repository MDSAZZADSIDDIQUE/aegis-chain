"""Agent Orchestrator — Multi-Agent Reflection Pipeline.

Coordinates the three-agent pipeline:
  Agent 1 (Watcher)     → Detect threats & predict bottlenecks
  Agent 2 (Procurement) → Score suppliers & propose reroutes
  Agent 3 (Auditor)     → Reflect, apply RL, enforce HITL thresholds

Runs as a scheduled background task or can be triggered manually.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.watcher import run_watcher_cycle
from app.agents.procurement import run_procurement_cycle
from app.agents.auditor import run_auditor_cycle
from app.services.slack import send_hitl_approval_request
from app.core.config import settings

logger = logging.getLogger("aegis.orchestrator")


async def run_full_pipeline() -> dict[str, Any]:
    """Execute the complete three-agent reflection pipeline."""
    pipeline_result: dict[str, Any] = {
        "watcher": {},
        "procurement": [],
        "auditor": [],
        "actions_taken": [],
    }

    # ── Agent 1: Watcher ─────────────────────────────────────────────
    logger.info("=== Pipeline: Running Agent 1 (Watcher) ===")
    watcher_result = await run_watcher_cycle()
    pipeline_result["watcher"] = {
        "bottleneck_count": len(watcher_result.get("bottleneck_predictions", [])),
        "at_risk_locations": len(watcher_result.get("at_risk_locations", [])),
        "total_value_at_risk": watcher_result.get("total_value_at_risk", 0),
        "threat_correlations": len(watcher_result.get("threat_correlations", [])),
    }

    correlations = watcher_result.get("threat_correlations", [])
    if not correlations:
        logger.info("No threat correlations found. Pipeline complete (no action needed).")
        return pipeline_result

    # ── Agent 2: Procurement — for each threat correlation ───────────
    logger.info("=== Pipeline: Running Agent 2 (Procurement) ===")
    all_proposals: list[dict[str, Any]] = []

    for corr in correlations:
        threat_id = corr["threat_id"]
        affected_locs = corr.get("affected_locations", [])

        if not affected_locs:
            continue

        # Use the highest-value affected location as the origin
        origin = max(affected_locs, key=lambda x: x.get("inventory_value_usd", 0))

        # We need the full origin doc with coordinates
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

        # Fetch threat details for centroid and zone
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
        all_proposals.extend(proposals)

    pipeline_result["procurement"] = [
        {
            "proposal_id": p["proposal_id"],
            "threat_id": p["threat_id"],
            "supplier": p["proposed_supplier_name"],
            "attention_score": p["attention_score"],
            "cost": p["reroute_cost_usd"],
        }
        for p in all_proposals
    ]

    if not all_proposals:
        logger.info("No reroute proposals generated. Pipeline complete.")
        return pipeline_result

    # ── Agent 3: Auditor — reflect on all proposals ──────────────────
    logger.info("=== Pipeline: Running Agent 3 (Auditor) ===")

    # Only send top proposal per threat to the Auditor
    best_per_threat: dict[str, dict] = {}
    for p in all_proposals:
        tid = p["threat_id"]
        if tid not in best_per_threat or p["attention_score"] > best_per_threat[tid]["attention_score"]:
            best_per_threat[tid] = p

    verdicts = await run_auditor_cycle(list(best_per_threat.values()))
    pipeline_result["auditor"] = verdicts

    # ── Execute actions based on verdicts ─────────────────────────────
    for verdict in verdicts:
        proposal_id = verdict["proposal_id"]
        proposal = best_per_threat.get(
            next(
                (p["threat_id"] for p in all_proposals if p["proposal_id"] == proposal_id),
                "",
            ),
            {},
        )

        if verdict["requires_hitl"]:
            # Send Slack approval
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
            pipeline_result["actions_taken"].append({
                "type": "hitl_slack_approval",
                "proposal_id": proposal_id,
                "slack_sent": sent,
            })
        elif verdict["approved"]:
            pipeline_result["actions_taken"].append({
                "type": "auto_executed",
                "proposal_id": proposal_id,
                "confidence": verdict["confidence"],
            })
        else:
            pipeline_result["actions_taken"].append({
                "type": "rejected",
                "proposal_id": proposal_id,
                "confidence": verdict["confidence"],
                "reason": verdict["explanation"],
            })

    logger.info(
        "Pipeline complete. Proposals: %d, Verdicts: %d, Actions: %d",
        len(all_proposals),
        len(verdicts),
        len(pipeline_result["actions_taken"]),
    )

    return pipeline_result
