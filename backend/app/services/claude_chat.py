"""Chat-to-Map reasoning layer — intent classification + ES|QL explanation via Claude."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger("aegis.services.claude_chat")

# ── Intent classifier prompt ─────────────────────────────────────────────────

_INTENT_SYSTEM = """\
You are an intent classifier for AegisChain, a real-time supply-chain risk platform.

Classify the operator's question into exactly one of these intents:
- supplier_ranking  : questions about vendors, suppliers, procurement, who to choose, SLA scores
- risk_assessment   : questions about threats, weather risks, value at risk, at-risk locations
- reroute_status    : questions about routes, reroutes, logistics proposals, diversions
- general           : anything that does not clearly match the above

Respond with ONLY valid JSON — no markdown, no prose:
{"intent": "<supplier_ranking|risk_assessment|reroute_status|general>"}"""

# ── Explanation prompt ───────────────────────────────────────────────────────

_EXPLAIN_SYSTEM = """\
You are AegisChain Analyst, an expert supply-chain intelligence assistant embedded in a \
real-time risk operations dashboard.

You are given:
1. An operator's question
2. The ES|QL query that was executed against Elasticsearch
3. The live query results as JSON

Your task: provide a concise, actionable answer in 2-4 sentences.
- Cite specific numbers or entity names from the results
- Surface the single most important insight the operator needs to act on
- Mention the ES|QL query briefly to emphasise auditability (e.g. "Based on the ES|QL query...")
- Do NOT repeat the raw JSON; synthesise it into plain language
- Do NOT use markdown headers or nested bullet lists; prose or a short flat list only"""

# ── ES|QL query catalog ──────────────────────────────────────────────────────

ESQL_SUPPLIER_RANKING = """\
FROM erp-locations
| WHERE type == "supplier" AND active == true
| LOOKUP JOIN `supplier-sla-scores` ON location_id
| EVAL sla = COALESCE(sla_score, 0.5)
| EVAL risk_adjusted_score = reliability_index * sla * (1.0 / (avg_lead_time_hours + 1.0))
| SORT risk_adjusted_score DESC
| LIMIT 10
| KEEP name, location_id, reliability_index, avg_lead_time_hours,
       sla_score, sla_tier, risk_adjusted_score, inventory_value_usd"""

ESQL_SUPPLIER_RANKING_FALLBACK = """\
FROM erp-locations
| WHERE type == "supplier" AND active == true
| EVAL risk_adjusted_score = reliability_index * (1.0 / (avg_lead_time_hours + 1.0))
| SORT risk_adjusted_score DESC
| LIMIT 10
| KEEP name, location_id, reliability_index, avg_lead_time_hours,
       risk_adjusted_score, inventory_value_usd"""

ESQL_RISK_ASSESSMENT = """\
FROM weather-threats
| WHERE status == "active"
| STATS threat_count = COUNT(*), severity_types = COUNT_DISTINCT(severity) BY event_type
| SORT threat_count DESC"""

# Reroute status is served from the proposals index via _list_proposals(),
# but we expose this string for auditability in the chat response.
ESQL_REROUTE_PROPOSALS = """\
FROM aegis-proposals
| WHERE hitl_status IN ("approved", "auto_approved")
| SORT created_at DESC
| LIMIT 5
| KEEP proposal_id, original_supplier_id, proposed_supplier_name,
       attention_score, mapbox_drive_time_minutes, rationale, created_at"""


# ── Public helpers ───────────────────────────────────────────────────────────

async def classify_intent(question: str) -> str:
    """Return one of: supplier_ranking | risk_assessment | reroute_status | general.

    Uses Claude Haiku for fast, cheap classification.  Falls back to keyword
    matching when ANTHROPIC_API_KEY is not configured.
    """
    if not settings.anthropic_api_key:
        logger.debug("No ANTHROPIC_API_KEY — using keyword intent fallback")
        return _keyword_fallback(question)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=40,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        intent = data.get("intent", "general")
        logger.debug("Claude classified intent: %r → %s", question[:60], intent)
        return intent
    except Exception as exc:
        logger.warning("Intent classification failed: %s — using keyword fallback", exc)
        return _keyword_fallback(question)


async def explain_results(
    question: str,
    esql_query: str,
    table: list[dict[str, Any]],
    context_threat_id: str | None = None,
) -> str:
    """Ask Claude Sonnet to synthesise ES|QL results into a natural-language explanation.

    Falls back to a minimal template when ANTHROPIC_API_KEY is not set.
    """
    if not settings.anthropic_api_key:
        logger.debug("No ANTHROPIC_API_KEY — using template explanation fallback")
        return _fallback_explanation(table)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    threat_note = (
        f"\nActive threat context: {context_threat_id}" if context_threat_id else ""
    )
    user_content = (
        f"Question: {question}{threat_note}\n\n"
        f"ES|QL query executed:\n{esql_query}\n\n"
        f"Results ({len(table)} row(s), showing top 10):\n"
        f"{json.dumps(table[:10], indent=2, default=str)}"
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=_EXPLAIN_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.warning("Claude explanation failed: %s — using template fallback", exc)
        return _fallback_explanation(table)


# ── Fallbacks when Claude API is unavailable ─────────────────────────────────

def _keyword_fallback(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ("supplier", "vendor", "sla", "procurement", "why")):
        return "supplier_ranking"
    if any(w in q for w in ("risk", "threat", "weather", "value", "at risk")):
        return "risk_assessment"
    if any(w in q for w in ("route", "reroute", "divert", "proposal", "logistics")):
        return "reroute_status"
    return "general"


def _fallback_explanation(table: list[dict[str, Any]]) -> str:
    if not table:
        return "No data found for your query."
    first = table[0]
    preview = ", ".join(f"{k}: {v}" for k, v in list(first.items())[:4])
    return (
        f"Query returned {len(table)} result(s). "
        f"Top entry — {preview}."
    )
