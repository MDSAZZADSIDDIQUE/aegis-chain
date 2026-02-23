"""NOAA National Weather Service API client.

Polls /alerts/active and converts alert zones into GeoJSON polygons
for indexing into the weather-threats index.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from app.core.config import settings

logger = logging.getLogger("aegis.noaa")

NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"

# NOAA severity → our normalized severity
_SEVERITY_MAP = {
    "Extreme": "extreme",
    "Severe": "severe",
    "Moderate": "moderate",
    "Minor": "minor",
}

# Event strings we care about for supply-chain disruption
_RELEVANT_EVENTS = {
    "Hurricane Warning", "Hurricane Watch",
    "Tropical Storm Warning", "Tropical Storm Watch",
    "Tornado Warning", "Tornado Watch",
    "Flood Warning", "Flash Flood Warning", "Flood Watch",
    "Winter Storm Warning", "Winter Storm Watch", "Blizzard Warning",
    "Ice Storm Warning",
    "Severe Thunderstorm Warning", "Severe Thunderstorm Watch",
    "Excessive Heat Warning", "Heat Advisory",
    "Red Flag Warning",  # wildfire conditions
}


def _parse_event_type(event: str) -> str:
    event_lower = event.lower()
    if "hurricane" in event_lower or "tropical" in event_lower:
        return "hurricane"
    if "tornado" in event_lower:
        return "tornado"
    if "flood" in event_lower:
        return "flood"
    if "winter" in event_lower or "blizzard" in event_lower or "ice storm" in event_lower:
        return "winter_storm"
    if "heat" in event_lower:
        return "heat_wave"
    if "thunderstorm" in event_lower:
        return "severe_thunderstorm"
    if "fire" in event_lower or "red flag" in event_lower:
        return "wildfire"
    return "unknown"


async def _fetch_zone_geometry(zone_url: str, client: httpx.AsyncClient) -> dict | None:
    """Fetch the GeoJSON geometry for a NOAA forecast zone."""
    try:
        resp = await client.get(zone_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        geom = data.get("geometry")
        if geom and geom.get("coordinates"):
            return geom
    except Exception as exc:
        logger.warning("Failed to fetch zone geometry %s: %s", zone_url, exc)
    return None


async def fetch_noaa_alerts() -> list[dict[str, Any]]:
    """Return a list of weather-threat docs ready for Elasticsearch."""
    headers = {"User-Agent": settings.noaa_user_agent, "Accept": "application/geo+json"}
    threats: list[dict[str, Any]] = []

    async with httpx.AsyncClient(headers=headers) as client:
        resp = await client.get(NOAA_ALERTS_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        logger.info("NOAA returned %d active alerts", len(features))

        for feat in features:
            props = feat.get("properties", {})
            event = props.get("event", "")

            if event not in _RELEVANT_EVENTS:
                continue

            alert_id = props.get("id", props.get("@id", ""))

            # Build the affected zone polygon
            geom = feat.get("geometry")
            if geom and geom.get("coordinates"):
                affected_zone = geom
            else:
                # Fetch geometry from affected zone URLs
                zone_urls = [
                    f"https://api.weather.gov/zones/forecast/{z}"
                    for z in (props.get("affectedZones") or [])
                ]
                zone_geoms = []
                for url in zone_urls[:5]:  # cap to avoid too many requests
                    zg = await _fetch_zone_geometry(url, client)
                    if zg:
                        zone_geoms.append(shape(zg))

                if not zone_geoms:
                    logger.debug("Skipping alert %s — no geometry resolved", alert_id)
                    continue

                merged = unary_union(zone_geoms)
                affected_zone = mapping(merged)

            # Compute centroid
            shp = shape(affected_zone)
            centroid = shp.centroid
            centroid_dict = {"lat": centroid.y, "lon": centroid.x}

            threats.append({
                "threat_id": alert_id,
                "source": "noaa",
                "event_type": _parse_event_type(event),
                "severity": _SEVERITY_MAP.get(props.get("severity", ""), "unknown"),
                "certainty": (props.get("certainty") or "unknown").lower(),
                "urgency": (props.get("urgency") or "unknown").lower(),
                "headline": props.get("headline", ""),
                "description": props.get("description", ""),
                "affected_zone": affected_zone,
                "centroid": centroid_dict,
                "effective": props.get("effective"),
                "expires": props.get("expires"),
                "onset": props.get("onset"),
                "status": "active",
                "nws_zone_ids": props.get("affectedZones", []),
                "raw_payload": props,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })

    logger.info("Parsed %d supply-relevant NOAA threats", len(threats))
    return threats
