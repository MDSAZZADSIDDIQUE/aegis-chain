"""NASA FIRMS (Fire Information for Resource Management System) client.

Polls the FIRMS CSV API for active fire detections (VIIRS/MODIS),
clusters nearby fire points into polygons, and produces weather-threat
docs for Elasticsearch.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from itertools import groupby
from typing import Any

import httpx
import numpy as np
from shapely.geometry import MultiPoint, mapping
from shapely.validation import make_valid

from app.core.config import settings

logger = logging.getLogger("aegis.firms")

# VIIRS SNPP active fires — last 24 hours, US region
FIRMS_CSV_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
    "{map_key}/VIIRS_SNPP_NRT/USA/1"
)

# Minimum confidence to include a detection
MIN_CONFIDENCE = 50

# Buffer radius (degrees ≈ km / 111) around fire clusters to form polygons
CLUSTER_BUFFER_DEG = 0.15  # ~16.7 km


def _parse_confidence(conf_raw: str) -> int:
    """Map FIRMS confidence field to 0-100 integer.
    Handles MODIS (0-100) and VIIRS (l/n/h).
    """
    conf_raw = conf_raw.lower().strip()
    if conf_raw == "h":
        return 100
    elif conf_raw == "n":
        return 70
    elif conf_raw == "l":
        return 30
    else:
        try:
            return int(conf_raw.rstrip("%"))
        except ValueError:
            return 0


def _cluster_fires(
    points: list[tuple[float, float]],
    eps_deg: float = 0.25,
) -> list[list[tuple[float, float]]]:
    """Simple grid-based spatial clustering of fire detections.

    Groups nearby fire points within `eps_deg` grid cells so we can form
    meaningful polygons instead of indexing thousands of individual points.
    """
    if not points:
        return []

    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lon, lat in points:
        key = (int(lon / eps_deg), int(lat / eps_deg))
        buckets.setdefault(key, []).append((lon, lat))

    # Merge adjacent cells using simple flood fill
    visited: set[tuple[int, int]] = set()
    clusters: list[list[tuple[float, float]]] = []

    def flood(key: tuple[int, int], acc: list[tuple[float, float]]) -> None:
        if key in visited or key not in buckets:
            return
        visited.add(key)
        acc.extend(buckets[key])
        gx, gy = key
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                flood((gx + dx, gy + dy), acc)

    for key in buckets:
        if key not in visited:
            cluster: list[tuple[float, float]] = []
            flood(key, cluster)
            if cluster:
                clusters.append(cluster)

    return clusters


async def fetch_firms_fires() -> list[dict[str, Any]]:
    """Return weather-threat docs for active wildfire clusters."""
    url = FIRMS_CSV_URL.format(map_key=settings.nasa_firms_map_key)
    threats: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        logger.info("FIRMS returned %d fire detections", len(rows))

        # Filter by confidence
        valid_rows = []
        for row in rows:
            conf = _parse_confidence(row.get("confidence", "0"))
            if conf >= MIN_CONFIDENCE:
                valid_rows.append(row)

        # Extract points
        fire_points: list[tuple[float, float, dict]] = []
        for row in valid_rows:
            try:
                lon = float(row["longitude"])
                lat = float(row["latitude"])
            except (KeyError, ValueError):
                continue
            fire_points.append((lon, lat, row))

        if not fire_points:
            return threats

        # Cluster fire detections into polygons
        point_coords = [(lon, lat) for lon, lat, _ in fire_points]
        clusters = _cluster_fires(point_coords)

        for idx, cluster_pts in enumerate(clusters):
            if len(cluster_pts) < 2:
                # Single point — buffer into circle
                mp = MultiPoint([(p[0], p[1]) for p in cluster_pts])
                poly = mp.centroid.buffer(CLUSTER_BUFFER_DEG)
            else:
                mp = MultiPoint([(p[0], p[1]) for p in cluster_pts])
                poly = mp.convex_hull.buffer(CLUSTER_BUFFER_DEG)

            # Ensure the geometry is valid and rings are properly closed
            if not poly.is_valid:
                poly = make_valid(poly)

            centroid = poly.centroid
            # Elasticsearch requires GeoJSON [Longitude, Latitude] order.
            # Shapely and mapping() already output this correctly.
            affected_zone = mapping(poly)

            # Aggregate cluster metadata
            cluster_rows = [
                row for lon, lat, row in fire_points
                if (lon, lat) in cluster_pts
            ]
            avg_brightness = np.mean([
                float(r.get("bright_ti4", 0) or 0) for r in cluster_rows
            ]) if cluster_rows else 0.0
            avg_frp = np.mean([
                float(r.get("frp", 0) or 0) for r in cluster_rows
            ]) if cluster_rows else 0.0
            avg_conf = np.mean([
                _parse_confidence(r.get("confidence", "0"))
                for r in cluster_rows
            ]) if cluster_rows else 0.0

            threat_id = f"firms-cluster-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{idx:04d}"

            threats.append({
                "threat_id": threat_id,
                "source": "nasa_firms",
                "event_type": "wildfire",
                "severity": "severe" if avg_frp > 50 else "moderate",
                "certainty": "observed",
                "urgency": "immediate",
                "headline": f"Active wildfire cluster ({len(cluster_pts)} detections)",
                "description": (
                    f"VIIRS SNPP detected {len(cluster_pts)} active fire points. "
                    f"Avg brightness: {avg_brightness:.0f}K, Avg FRP: {avg_frp:.1f}MW."
                ),
                "affected_zone": affected_zone,
                "centroid": {"lat": centroid.y, "lon": centroid.x},
                "effective": datetime.now(timezone.utc).isoformat(),
                "expires": None,
                "status": "active",
                "confidence_pct": round(avg_conf, 1),
                "brightness_kelvin": round(avg_brightness, 1),
                "frp_mw": round(avg_frp, 2),
                "raw_payload": {"detection_count": len(cluster_pts)},
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })

    logger.info("Produced %d wildfire threat polygons from FIRMS", len(threats))
    return threats
