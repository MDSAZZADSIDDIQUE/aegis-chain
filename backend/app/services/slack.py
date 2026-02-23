"""Slack webhook client for Human-in-the-Loop (HITL) approval flows.

Sends interactive messages with Approve/Reject buttons when a reroute
proposal exceeds the $50k threshold (Agent 3 Auditor).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("aegis.slack")


async def send_hitl_approval_request(
    proposal_id: str,
    threat_headline: str,
    original_supplier: str,
    proposed_supplier: str,
    reroute_cost: float,
    attention_score: float,
    drive_time_min: float,
    rationale: str,
) -> bool:
    """Post an interactive Slack message requesting HITL approval."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":rotating_light: AegisChain — HITL Approval Required",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Threat:*\n{threat_headline}"},
                {"type": "mrkdwn", "text": f"*Proposal ID:*\n`{proposal_id}`"},
                {"type": "mrkdwn", "text": f"*Current Supplier:*\n{original_supplier}"},
                {"type": "mrkdwn", "text": f"*Proposed Supplier:*\n{proposed_supplier}"},
                {"type": "mrkdwn", "text": f"*Reroute Cost:*\n${reroute_cost:,.2f}"},
                {"type": "mrkdwn", "text": f"*Attention Score:*\n{attention_score:.4f}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Drive Time (around hazard):* {drive_time_min:.0f} min\n"
                    f"*Agent Rationale:*\n>{rationale}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": f"hitl_{proposal_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "hitl_approve",
                    "value": proposal_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "hitl_reject",
                    "value": proposal_id,
                },
            ],
        },
    ]

    payload = {"blocks": blocks, "text": f"HITL Approval: {proposal_id}"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            settings.slack_webhook_url,
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("HITL approval request sent for %s", proposal_id)
            return True
        else:
            logger.error("Slack webhook failed: %s %s", resp.status_code, resp.text)
            return False


def verify_slack_signature(
    timestamp: str,
    body: bytes,
    signature: str,
) -> bool:
    """Verify that an incoming request actually came from Slack."""
    if abs(time.time() - int(timestamp)) > 300:
        return False  # request too old — replay attack prevention

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(computed, signature)
