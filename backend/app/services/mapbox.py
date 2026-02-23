"""Mapbox Directions API client.

Calculates actual drive-time routes, used by Agent 2 (Procurement) to
verify reroute feasibility with real road network data.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("aegis.mapbox")

DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"


async def get_route(
    origin_lon: float,
    origin_lat: float,
    dest_lon: float,
    dest_lat: float,
    avoid_polygon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query Mapbox Directions for a driving route.

    Returns distance_km, duration_minutes, and the GeoJSON LineString
    geometry of the route.

    If `avoid_polygon` is supplied (GeoJSON dict), we pass it as an
    exclusion via the Mapbox `exclude` parameter.  Mapbox's free tier
    doesn't support arbitrary polygon exclusions, so as a fallback we
    add a waypoint that routes around the polygon centroid.
    """
    coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    params: dict[str, str] = {
        "access_token": settings.mapbox_access_token,
        "geometries": "geojson",
        "overview": "full",
        "annotations": "duration,distance",
    }

    # If we have an avoidance polygon, inject a midpoint waypoint that
    # pushes the route away from the hazard centroid.
    if avoid_polygon:
        try:
            from shapely.geometry import shape
            hazard = shape(avoid_polygon)
            cx, cy = hazard.centroid.x, hazard.centroid.y
            # Push waypoint 0.5° perpendicular from centroid
            # (simple heuristic — north offset)
            mid_lon = (origin_lon + dest_lon) / 2
            mid_lat = (origin_lat + dest_lat) / 2
            # Offset away from hazard
            dx = mid_lon - cx
            dy = mid_lat - cy
            norm = (dx**2 + dy**2) ** 0.5 or 1
            offset_lon = mid_lon + 0.5 * dx / norm
            offset_lat = mid_lat + 0.5 * dy / norm
            coords = (
                f"{origin_lon},{origin_lat};"
                f"{offset_lon},{offset_lat};"
                f"{dest_lon},{dest_lat}"
            )
        except Exception as exc:
            logger.warning("Failed to compute avoidance waypoint: %s", exc)

    url = f"{DIRECTIONS_URL}/{coords}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

    routes = data.get("routes", [])
    if not routes:
        raise ValueError("Mapbox returned no routes")

    best = routes[0]
    distance_m = best["distance"]
    duration_s = best["duration"]

    return {
        "distance_km": round(distance_m / 1000, 2),
        "duration_minutes": round(duration_s / 60, 2),
        "geometry": best["geometry"],
    }
