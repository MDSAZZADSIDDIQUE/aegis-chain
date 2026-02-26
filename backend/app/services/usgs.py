"""USGS Earthquake Hazards GeoJSON client.

Polls the USGS real-time earthquake feed, converts events above a
configurable magnitude threshold into weather-threat documents with
buffered affected-zone polygons proportional to earthquake magnitude.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely.geometry import Point, mapping
from shapely.validation import make_valid

logger = logging.getLogger("aegis.usgs")

# USGS GeoJSON feed — all M2.5+ earthquakes in the last day
USGS_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"

# Only ingest earthquakes at or above this magnitude for supply-chain relevance
MIN_MAGNITUDE = 4.0

# Magnitude → AegisChain severity mapping
_SEVERITY_MAP: list[tuple[float, str]] = [
    (7.0, "extreme"),
    (6.0, "severe"),
    (5.0, "moderate"),
    (0.0, "minor"),
]


def _mag_to_severity(mag: float) -> str:
    for threshold, severity in _SEVERITY_MAP:
        if mag >= threshold:
            return severity
    return "minor"


def _mag_to_buffer_km(mag: float) -> float:
    """Approximate felt-radius in km based on magnitude.

    Uses a simplified version of the USGS ShakeMap attenuation relation.
    M4 → ~30 km, M5 → ~75 km, M6 → ~180 km, M7+ → ~400 km.
    """
    return min(10 ** (0.5 * mag - 0.8), 600)


async def fetch_usgs_earthquakes() -> list[dict[str, Any]]:
    """Fetch recent USGS earthquakes and convert to threat documents.

    Returns a list of threat dicts compatible with ``index_threats()``.
    """
    threats: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(USGS_FEED_URL)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("USGS feed fetch failed: %s", exc)
            return threats

    features = data.get("features", [])
    logger.info("USGS feed returned %d earthquakes (filtering M≥%.1f)", len(features), MIN_MAGNITUDE)

    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        mag = props.get("mag")
        if mag is None or mag < MIN_MAGNITUDE:
            continue

        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        depth_km = coords[2] if len(coords) > 2 else 0.0

        # Unique threat ID from USGS event code
        usgs_id = feat.get("id", f"usgs-{lon}-{lat}-{mag}")
        threat_id = f"usgs-{usgs_id}"

        # Generate affected zone polygon by buffering epicenter
        buffer_km = _mag_to_buffer_km(mag)
        buffer_deg = buffer_km / 111.0  # approximate degrees

        try:
            epicenter = Point(lon, lat)
            buffered = epicenter.buffer(buffer_deg, resolution=32)
            if not buffered.is_valid:
                buffered = make_valid(buffered)
            affected_zone = mapping(buffered)
        except Exception as exc:
            logger.warning("Failed to buffer epicenter for %s: %s", threat_id, exc)
            continue

        severity = _mag_to_severity(mag)
        place = props.get("place", "Unknown location")
        event_time_ms = props.get("time")
        event_time = (
            datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc).isoformat()
            if event_time_ms
            else datetime.now(timezone.utc).isoformat()
        )

        # Tsunami advisory flag from USGS
        tsunami = props.get("tsunami", 0)
        event_type = "tsunami" if tsunami == 1 and mag >= 6.5 else "earthquake"

        threats.append({
            "threat_id": threat_id,
            "source": "usgs",
            "event_type": event_type,
            "severity": severity,
            "certainty": "observed",
            "urgency": "immediate" if mag >= 6.0 else "expected",
            "headline": f"M{mag:.1f} earthquake — {place}",
            "description": (
                f"USGS reported a magnitude {mag:.1f} earthquake at depth {depth_km:.1f} km. "
                f"Estimated felt radius: {buffer_km:.0f} km. "
                f"{'Tsunami advisory issued.' if tsunami else ''}"
            ).strip(),
            "affected_zone": affected_zone,
            "future_zones": [],
            "centroid": {"lat": lat, "lon": lon},
            "effective": event_time,
            "expires": None,
            "status": "active",
            "magnitude": mag,
            "depth_km": depth_km,
            "tsunami_advisory": bool(tsunami),
            "raw_payload": {
                "usgs_id": usgs_id,
                "url": props.get("url", ""),
                "felt": props.get("felt"),
                "cdi": props.get("cdi"),
                "mmi": props.get("mmi"),
                "alert": props.get("alert"),
            },
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

    logger.info(
        "Produced %d earthquake threat polygons from USGS (M≥%.1f)",
        len(threats), MIN_MAGNITUDE,
    )
    return threats
