"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import mapboxgl from "mapbox-gl";
import * as turf from "@turf/turf";
import type { WeatherThreat, ERPLocation, Proposal } from "@/lib/api";

// Hazard palette — orange/red, no blues or purples
const SEVERITY_COLORS: Record<string, string> = {
  extreme:  "#dc2626", // red-600
  severe:   "#ea580c", // orange-600
  moderate: "#d97706", // amber-600
  minor:    "#ca8a04", // yellow-600
  unknown:  "#78716c", // stone-500
};

// Location type → bio-lime / canopy palette
const LOCATION_COLORS: Record<string, string> = {
  warehouse:           "#4ade80", // green-400
  supplier:            "#a3e635", // lime-400
  distribution_center: "#34d399", // emerald-400
  port:                "#86efac", // green-300
};

interface AegisGlobeProps {
  threats: WeatherThreat[];
  locations: ERPLocation[];
  routes: Proposal[];
  highlightedEntities: string[];
  selectedThreatId?: string;
  onLocationClick?: (location: ERPLocation) => void;
  onThreatClick?: (threat: WeatherThreat) => void;
}

export default function AegisGlobe({
  threats,
  locations,
  routes,
  highlightedEntities,
  selectedThreatId,
  onLocationClick,
  onThreatClick,
}: AegisGlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const initializedRef = useRef(false);
  
  // Keep handlers in refs so map listeners always use latest version 
  // without needing to re-initialize the entire map.
  const onLocationClickRef = useRef(onLocationClick);
  const onThreatClickRef = useRef(onThreatClick);

  useEffect(() => {
    onLocationClickRef.current = onLocationClick;
    onThreatClickRef.current = onThreatClick;
  }, [onLocationClick, onThreatClick]);

  // ── Initialize map ──────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || initializedRef.current) return;
    initializedRef.current = true;

    mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

    const map = new mapboxgl.Map({
      container: containerRef.current,
      // Satellite-streets hybrid: actual agricultural land imagery + road network
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      projection: "globe",
      center: [-98, 38],
      zoom: 3.5,
      pitch: 25,
      bearing: -8,
      antialias: true,
    });

    map.on("style.load", () => {
      // ── Load Custom SVG Icons ───────────────────────────────────
      const loadIcon = (id: string, svg: string) => {
        const img = new Image(24, 24);
        img.onload = () => {
          if (!map.hasImage(id)) map.addImage(id, img);
        };
        img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
      };

      loadIcon("icon-warehouse", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M3 21V8l9-4 9 4v13 M13 21v-8h-2v8 M9 21v-4H5v4" fill="none" stroke="#020617" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
      loadIcon("icon-supplier", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 21c0-4 2-6 6-8 3-1 4-3 2-6-2-2-5-1-6 2-1 2-2 4-2 12Z M6 22c0-2.5 1.5-4 4-5" fill="none" stroke="#020617" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
      loadIcon("icon-distribution_center", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 5v14M8 9l4-4 4 4M5 12h14M8 15l4 4 4-4" fill="none" stroke="#020617" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
      loadIcon("icon-port", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="5" r="2" fill="none" stroke="#020617" stroke-width="2.5"/><path d="M12 22V7M6 12H3a8 8 0 0 0 18 0h-3M12 22c-2 0-3-1.5-4-3l-2-7M12 22c2 0 3-1.5 4-3l2-7" fill="none" stroke="#020617" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`);


      // Atmosphere — earthy, deep-field agricultural night sky
      map.setFog({
        color: "rgb(12, 10, 9)",          // stone-950 horizon haze
        "high-color": "rgb(10, 30, 18)",  // deep canopy green upper atmosphere
        "horizon-blend": 0.06,
        "space-color": "rgb(4, 4, 4)",    // near-black space
        "star-intensity": 0.65,           // visible stars over agricultural fields at night
      });

      // 3D Terrain — added for depth and tactical relief
      map.addSource("mapbox-dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
      map.setTerrain({ source: "mapbox-dem", exaggeration: 1.5 });

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
            3, 8,
            8, 14,
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
        id: "erp-icons",
        type: "symbol",
        source: "erp-locations",
        layout: {
          "icon-image": ["concat", "icon-", ["get", "type"]],
          "icon-size": [
            "interpolate", ["linear"], ["zoom"],
            3, 0.45,
            8, 0.8,
          ],
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
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
            ["==", ["get", "status"], "approved"],          "#a3e635", // lime-400
            ["==", ["get", "status"], "awaiting_approval"], "#f59e0b", // amber-500
            "#84cc16", // lime-500 default
          ],
          "line-width": 2.5,
          "line-opacity": 0.9,
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
          "text-color": "#a3e635", // lime-400 arrows
        },
      });

      // ── Click handlers ──────────────────────────────────────────
      ["erp-points", "erp-icons"].forEach(layer => {
        map.on("click", layer, (e) => {
          if (!e.features?.[0]) return;
          const props = e.features[0].properties;
          if (onLocationClickRef.current && props) {
            onLocationClickRef.current(props as unknown as ERPLocation);
          }
        });
      });

      map.on("click", "threat-fills", (e) => {
        if (!e.features?.[0]) return;
        const props = e.features[0].properties;
        if (onThreatClickRef.current && props) {
          onThreatClickRef.current(props as unknown as WeatherThreat);
        }
      });

      // Cursor changes
      ["erp-points", "erp-icons"].forEach(layer => {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
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

      ["erp-points", "erp-icons"].forEach(layer => {
        map.on("mouseenter", layer, (e) => {
          if (!e.features?.[0]) return;
          const p = e.features[0].properties!;
          const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];
          popup
            .setLngLat(coords)
            .setHTML(
              `<div style="font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.8;min-width:180px;">
                <div style="font-size:11px;font-weight:700;color:#e7e5e4;margin-bottom:6px;letter-spacing:0.02em;">
                  ${p.name}
                </div>
                <div style="color:#78716c;font-size:9px;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">
                  ${(p.type as string).replace("_"," ")}
                </div>
                <div style="display:grid;grid-template-columns:auto 1fr;gap:2px 8px;">
                  <span style="color:#78716c;font-size:9px;">RELIABILITY</span>
                  <span style="color:#a3e635;">${Number(p.reliability_index).toFixed(3)}</span>
                  <span style="color:#78716c;font-size:9px;">INV VALUE</span>
                  <span style="color:#a3e635;">$${Number(p.inventory_value_usd).toLocaleString()}</span>
                  <span style="color:#78716c;font-size:9px;">LEAD TIME</span>
                  <span style="color:#a3e635;">${Number(p.avg_lead_time_hours ?? 0).toFixed(1)}h</span>
                </div>
              </div>`
            )
            .addTo(map);
        });

        map.on("mouseleave", layer, () => popup.remove());
      });

      // ── Map Animations ──────────────────────────────────────────
      let animationId: number;
      function animate() {
        if (!map || !map.isStyleLoaded()) return;
        const now = Date.now();
        
        // Threat Pulse (3 sec cycle)
        if (map.getLayer("threat-pulse")) {
          const t1 = (now % 3000) / 3000;
          const radiusMult = 1 + t1 * 1.5;
          const mapZoom = map.getZoom();
          const baseRadius = mapZoom < 6 ? 6 : 12;
          map.setPaintProperty("threat-pulse", "circle-radius", baseRadius * radiusMult);
          map.setPaintProperty("threat-pulse", "circle-opacity", 0.8 * (1 - t1));
        }

        // Route Pulse (2 sec cycle)
        if (map.getLayer("route-lines")) {
          const t2 = (now % 2000) / 2000;
          const width = 2.5 + Math.sin(t2 * Math.PI * 2) * 1.5;
          map.setPaintProperty("route-lines", "line-width", width);
        }

        animationId = requestAnimationFrame(animate);
      }
      animate();
    });

    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    mapRef.current = map;

    return () => {
      map.remove();
      initializedRef.current = false;
    };
  }, []); // Only initialize once on mount

  // ── Update threat polygons ────────────────────────────────────
  const updateThreats = () => {
    const map = mapRef.current;
    if (!map) return;

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

    console.log(`[AegisGlobe] Setting threat source data with ${features.length} features`, features[0]);
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

    console.log(`[AegisGlobe] Setting threat-centroids data with ${centroidFeatures.length} features`);
    centroidSource.setData({ type: "FeatureCollection", features: centroidFeatures });
  };

  // ── Update ERP locations ──────────────────────────────────────
  const updateLocations = () => {
    const map = mapRef.current;
    if (!map) return;

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
        avg_lead_time_hours: loc.avg_lead_time_hours,
        color: LOCATION_COLORS[loc.type] || "#6b7280",
        highlighted: highlightedEntities.includes(loc.location_id) || highlightedEntities.includes(loc.name),
      },
      geometry: {
        type: "Point",
        coordinates: [loc.coordinates.lon, loc.coordinates.lat],
      },
    }));

    console.log(`[AegisGlobe] Setting erp-locations data with ${features.length} features`, features[0]);
    source.setData({ type: "FeatureCollection", features });
  };

  // ── Update route lines ────────────────────────────────────────
  const updateRoutes = () => {
    const map = mapRef.current;
    if (!map) return;

    const source = map.getSource("routes") as mapboxgl.GeoJSONSource;
    if (!source) return;

    const features: GeoJSON.Feature[] = [];

    for (const route of routes) {
      const origin = locations.find((l) => l.location_id === route.original_supplier_id);
      const dest   = locations.find((l) => l.location_id === route.proposed_supplier_id);
      if (!origin || !dest) continue;

      // Prefer the real Mapbox road geometry stored on the proposal.
      // Fall back to a turf great-circle arc which looks far better than a
      // two-point straight line on a 3-D globe projection.
      let lineGeometry: GeoJSON.Geometry;
      if (route.route_geometry) {
        lineGeometry = route.route_geometry;
      } else {
        const arc = turf.greatCircle(
          turf.point([origin.coordinates.lon, origin.coordinates.lat]),
          turf.point([dest.coordinates.lon,   dest.coordinates.lat]),
          { npoints: 100 },
        );
        lineGeometry = arc.geometry;
      }

      features.push({
        type: "Feature",
        properties: {
          proposal_id:    route.proposal_id,
          status:         route.hitl_status || "pending",
          cost:           route.reroute_cost_usd,
          attention_score: route.attention_score,
        },
        geometry: lineGeometry,
      });
    }

    source.setData({ type: "FeatureCollection", features });
  };

  // ── Sync data to map when props change ────────────────────────
  // To bypass ALL React strict-mode mounting and Mapbox `style.load` vs 
  // `sourcedata` race conditions, we use an interval to continuously 
  // attempt to sync until the sources are actually ready and the data is loaded.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const interval = setInterval(() => {
      if (!map.isStyleLoaded()) return; // Wait for style

      let allSourcesReady = true;
      for (const id of ["threats", "threat-centroids", "erp-locations", "routes"]) {
        if (!map.getSource(id)) {
          allSourcesReady = false;
          break;
        }
      }

      if (allSourcesReady) {
        clearInterval(interval);
        console.log(`[AegisGlobe] Sources verified ready. Pushing data. threats:${threats.length} locs:${locations.length}`);
        updateThreats();
        updateLocations();
        updateRoutes();
      }
    }, 100);

    return () => clearInterval(interval);
  }, [threats, locations, routes, highlightedEntities]);

  // ── Make sure painting reacts to selectedThreatId changes ─────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (map.getLayer("threat-fills")) {
      map.setPaintProperty("threat-fills", "fill-opacity", [
        "case",
        ["==", ["get", "threat_id"], selectedThreatId || ""], 0.6,
        0.25
      ]);

      map.setPaintProperty("threat-borders", "line-width", [
        "case",
        ["==", ["get", "threat_id"], selectedThreatId || ""], 4,
        2
      ]);

      map.setPaintProperty("threat-pulse", "circle-radius", [
        "interpolate", ["linear"], ["zoom"],
        3, ["case", ["==", ["get", "threat_id"], selectedThreatId || ""], 12, 8],
        8, ["case", ["==", ["get", "threat_id"], selectedThreatId || ""], 24, 16],
      ]);
      
      map.setPaintProperty("threat-pulse", "circle-opacity", [
        "case",
        ["==", ["get", "threat_id"], selectedThreatId || ""], 0.9,
        0.6
      ]);
    }

    // Move camera 
    if (selectedThreatId) {
      const threat = threats.find((t) => t.threat_id === selectedThreatId);
      if (threat?.centroid) {
        map.flyTo({
          center: [threat.centroid.lon, threat.centroid.lat],
          zoom: 5.5,
          pitch: 45,
          speed: 1.2,
          essential: true,
        });
      }
    }
  }, [selectedThreatId, threats]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", position: "absolute", top: 0, left: 0 }}
    />
  );
}
