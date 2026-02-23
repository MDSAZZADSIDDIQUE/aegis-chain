"""Pydantic models for API request/response payloads and internal data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Weather / Threat models ──────────────────────────────────────────

class GeoJSONPolygon(BaseModel):
    type: str = "Polygon"
    coordinates: list[list[list[float]]]


class WeatherThreat(BaseModel):
    threat_id: str
    source: str  # noaa | nasa_firms
    event_type: str
    severity: str
    certainty: str = "unknown"
    urgency: str = "unknown"
    headline: str = ""
    description: str = ""
    affected_zone: dict[str, Any]  # GeoJSON
    centroid: dict[str, float] | None = None  # {"lat": ..., "lon": ...}
    effective: datetime | None = None
    expires: datetime | None = None
    onset: datetime | None = None
    status: str = "active"
    nws_zone_ids: list[str] = Field(default_factory=list)
    confidence_pct: float | None = None
    brightness_kelvin: float | None = None
    frp_mw: float | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


# ── Agent / Routing models ───────────────────────────────────────────

class RerouteProposal(BaseModel):
    proposal_id: str
    threat_id: str
    original_supplier_id: str
    proposed_supplier_id: str
    proposed_supplier_name: str
    attention_score: float
    mapbox_drive_time_minutes: float
    mapbox_distance_km: float
    reroute_cost_usd: float
    rationale: str


class AuditVerdict(BaseModel):
    proposal_id: str
    approved: bool
    confidence: float
    cost_usd: float
    requires_hitl: bool
    hitl_status: str = "pending"  # pending | approved | rejected
    rl_adjustment: float = 0.0
    explanation: str = ""


# ── Mapbox request/response ──────────────────────────────────────────

class MapboxRouteRequest(BaseModel):
    origin_lon: float
    origin_lat: float
    destination_lon: float
    destination_lat: float
    avoid_polygon: dict[str, Any] | None = None  # GeoJSON polygon to avoid


class MapboxRouteResponse(BaseModel):
    distance_km: float
    duration_minutes: float
    geometry: dict[str, Any]  # GeoJSON LineString


# ── Slack HITL ────────────────────────────────────────────────────────

class SlackAction(BaseModel):
    proposal_id: str
    action: str  # approve | reject
    user_id: str = ""
    user_name: str = ""


# ── RL Update ─────────────────────────────────────────────────────────

class RLUpdate(BaseModel):
    supplier_id: str
    outcome: str  # success | failure
    delivery_delay_hours: float = 0.0


# ── Chat-to-Map ──────────────────────────────────────────────────────

class ChatQuery(BaseModel):
    question: str
    context_threat_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    esql_query: str | None = None
    highlighted_entities: list[str] = Field(default_factory=list)
    map_annotations: list[dict[str, Any]] = Field(default_factory=list)


# ── Dashboard state ──────────────────────────────────────────────────

class DashboardState(BaseModel):
    active_threats: list[dict[str, Any]]
    erp_locations: list[dict[str, Any]]
    active_routes: list[dict[str, Any]]
    pending_proposals: list[dict[str, Any]]
    total_value_at_risk: float
