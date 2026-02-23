"use client";

import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import type { WeatherThreat, ERPLocation, Proposal } from "@/lib/api";

const SEVERITY_COLORS: Record<string, string> = {
  extreme: "#ef4444",
  severe: "#f97316",
  moderate: "#f59e0b",
  minor: "#3b82f6",
  unknown: "#8b5cf6",
};

const LOCATION_COLORS: Record<string, string> = {
  warehouse: "#3b82f6",
  supplier: "#22c55e",
  distribution_center: "#06b6d4",
  port: "#8b5cf6",
};

interface AegisGlobeProps {
  threats: WeatherThreat[];
  locations: ERPLocation[];
  routes: Proposal[];
  highlightedEntities: string[];
  onLocationClick?: (location: ERPLocation) => void;
  onThreatClick?: (threat: WeatherThreat) => void;
}

export default function AegisGlobe({
  threats,
  locations,
  routes,
  highlightedEntities,
  onLocationClick,
  onThreatClick,
}: AegisGlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const initializedRef = useRef(false);

  // ── Initialize map ──────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || initializedRef.current) return;
    initializedRef.current = true;

    mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      projection: "globe",
      center: [-98, 38],
      zoom: 3.5,
      pitch: 30,
      bearing: -10,
      antialias: true,
    });

    map.on("style.load", () => {
      // Atmosphere / fog for globe effect
      map.setFog({
        color: "rgb(10, 14, 23)",
        "high-color": "rgb(20, 30, 60)",
        "horizon-blend": 0.08,
        "space-color": "rgb(5, 5, 15)",
        "star-intensity": 0.4,
      });

      // ── Threat polygon layer ────────────────────────────────────
      map.addSource("threats", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "threat-fills",
        type: "fill",
        source: "threats",
        paint: {
          "fill-color": ["get", "color"],
          "fill-opacity": 0.25,
        },
      });

      map.addLayer({
        id: "threat-borders",
        type: "line",
        source: "threats",
        paint: {
          "line-color": ["get", "color"],
          "line-width": 2,
          "line-opacity": 0.8,
          "line-dasharray": [2, 2],
        },
      });

      // ── Threat pulse layer (animated circles at centroids) ──────
      map.addSource("threat-centroids", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "threat-pulse",
        type: "circle",
        source: "threat-centroids",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            3, 8,
            8, 16,
          ],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.6,
          "circle-stroke-width": 2,
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-opacity": 0.9,
        },
      });

      // ── ERP location points ─────────────────────────────────────
      map.addSource("erp-locations", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "erp-points",
        type: "circle",
        source: "erp-locations",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            3, 5,
            8, 10,
          ],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.9,
          "circle-stroke-width": [
            "case",
            ["get", "highlighted"], 3,
            1,
          ],
          "circle-stroke-color": [
            "case",
            ["get", "highlighted"], "#ffffff",
            ["get", "color"],
          ],
        },
      });

      map.addLayer({
        id: "erp-labels",
        type: "symbol",
        source: "erp-locations",
        layout: {
          "text-field": ["get", "name"],
          "text-size": 11,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          "text-font": ["DIN Pro Medium", "Arial Unicode MS Regular"],
        },
        paint: {
          "text-color": "#e2e8f0",
          "text-halo-color": "#0a0e17",
          "text-halo-width": 1.5,
        },
        minzoom: 5,
      });

      // ── Route lines ─────────────────────────────────────────────
      map.addSource("routes", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "route-lines",
        type: "line",
        source: "routes",
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
        paint: {
          "line-color": [
            "case",
            ["==", ["get", "status"], "approved"], "#22c55e",
            ["==", ["get", "status"], "awaiting_approval"], "#f59e0b",
            "#3b82f6",
          ],
          "line-width": 3,
          "line-opacity": 0.85,
        },
      });

      map.addLayer({
        id: "route-arrows",
        type: "symbol",
        source: "routes",
        layout: {
          "symbol-placement": "line",
          "symbol-spacing": 80,
          "text-field": "\u25B6",
          "text-size": 14,
          "text-keep-upright": false,
          "text-rotation-alignment": "map",
        },
        paint: {
          "text-color": "#22c55e",
        },
      });

      // ── Click handlers ──────────────────────────────────────────
      map.on("click", "erp-points", (e) => {
        if (!e.features?.[0]) return;
        const props = e.features[0].properties;
        if (onLocationClick && props) {
          onLocationClick(props as unknown as ERPLocation);
        }
      });

      map.on("click", "threat-fills", (e) => {
        if (!e.features?.[0]) return;
        const props = e.features[0].properties;
        if (onThreatClick && props) {
          onThreatClick(props as unknown as WeatherThreat);
        }
      });

      // Cursor changes
      map.on("mouseenter", "erp-points", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "erp-points", () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("mouseenter", "threat-fills", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "threat-fills", () => {
        map.getCanvas().style.cursor = "";
      });

      // Popups on hover for ERP locations
      const popup = new mapboxgl.Popup({
        closeButton: false,
        closeOnClick: false,
      });

      map.on("mouseenter", "erp-points", (e) => {
        if (!e.features?.[0]) return;
        const p = e.features[0].properties!;
        const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        popup
          .setLngLat(coords)
          .setHTML(
            `<div style="font-family:Inter,sans-serif;font-size:13px;">
              <strong>${p.name}</strong><br/>
              <span style="color:#94a3b8">Type:</span> ${p.type}<br/>
              <span style="color:#94a3b8">Reliability:</span> ${Number(p.reliability_index).toFixed(3)}<br/>
              <span style="color:#94a3b8">Value:</span> $${Number(p.inventory_value_usd).toLocaleString()}
            </div>`
          )
          .addTo(map);
      });

      map.on("mouseleave", "erp-points", () => popup.remove());
    });

    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    mapRef.current = map;

    return () => {
      map.remove();
      initializedRef.current = false;
    };
  }, [onLocationClick, onThreatClick]);

  // ── Update threat polygons ────────────────────────────────────
  const updateThreats = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const threatSource = map.getSource("threats") as mapboxgl.GeoJSONSource;
    const centroidSource = map.getSource("threat-centroids") as mapboxgl.GeoJSONSource;
    if (!threatSource || !centroidSource) return;

    const features: GeoJSON.Feature[] = threats.map((t) => ({
      type: "Feature",
      properties: {
        threat_id: t.threat_id,
        event_type: t.event_type,
        severity: t.severity,
        headline: t.headline,
        color: SEVERITY_COLORS[t.severity] || SEVERITY_COLORS.unknown,
      },
      geometry: t.affected_zone,
    }));

    threatSource.setData({ type: "FeatureCollection", features });

    const centroidFeatures: GeoJSON.Feature[] = threats
      .filter((t) => t.centroid)
      .map((t) => ({
        type: "Feature",
        properties: {
          threat_id: t.threat_id,
          severity: t.severity,
          color: SEVERITY_COLORS[t.severity] || SEVERITY_COLORS.unknown,
        },
        geometry: {
          type: "Point",
          coordinates: [t.centroid!.lon, t.centroid!.lat],
        },
      }));

    centroidSource.setData({ type: "FeatureCollection", features: centroidFeatures });
  }, [threats]);

  // ── Update ERP locations ──────────────────────────────────────
  const updateLocations = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("erp-locations") as mapboxgl.GeoJSONSource;
    if (!source) return;

    const features: GeoJSON.Feature[] = locations.map((loc) => ({
      type: "Feature",
      properties: {
        location_id: loc.location_id,
        name: loc.name,
        type: loc.type,
        reliability_index: loc.reliability_index,
        inventory_value_usd: loc.inventory_value_usd,
        color: LOCATION_COLORS[loc.type] || "#6b7280",
        highlighted: highlightedEntities.includes(loc.location_id) || highlightedEntities.includes(loc.name),
      },
      geometry: {
        type: "Point",
        coordinates: [loc.coordinates.lon, loc.coordinates.lat],
      },
    }));

    source.setData({ type: "FeatureCollection", features });
  }, [locations, highlightedEntities]);

  // ── Update route lines ────────────────────────────────────────
  const updateRoutes = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("routes") as mapboxgl.GeoJSONSource;
    if (!source) return;

    // For routes without Mapbox geometry, draw straight lines between
    // origin and destination locations
    const features: GeoJSON.Feature[] = [];

    for (const route of routes) {
      const origin = locations.find((l) => l.location_id === route.original_supplier_id);
      const dest = locations.find((l) => l.location_id === route.proposed_supplier_id);

      if (origin && dest) {
        features.push({
          type: "Feature",
          properties: {
            proposal_id: route.proposal_id,
            status: route.hitl_status || "pending",
            cost: route.reroute_cost_usd,
            attention_score: route.attention_score,
          },
          geometry: {
            type: "LineString",
            coordinates: [
              [origin.coordinates.lon, origin.coordinates.lat],
              [dest.coordinates.lon, dest.coordinates.lat],
            ],
          },
        });
      }
    }

    source.setData({ type: "FeatureCollection", features });
  }, [routes, locations]);

  // ── Sync data to map when props change ────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (map.isStyleLoaded()) {
      updateThreats();
      updateLocations();
      updateRoutes();
    } else {
      map.once("style.load", () => {
        updateThreats();
        updateLocations();
        updateRoutes();
      });
    }
  }, [updateThreats, updateLocations, updateRoutes]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", position: "absolute", top: 0, left: 0 }}
    />
  );
}
