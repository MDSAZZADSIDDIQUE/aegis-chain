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
  const previousThreatIdRef = useRef<string | undefined>(undefined);
  
  const [styleLoaded, setStyleLoaded] = useState(false);
  
  // Keep handlers in refs so map listeners always use latest version 
  // without needing to re-initialize the entire map.
  const onLocationClickRef = useRef(onLocationClick);
  const onThreatClickRef = useRef(onThreatClick);
  
  // Keep rapidly-updating SWR state in refs to prevent interval tear-downs
  const threatsRef = useRef(threats);
  const locationsRef = useRef(locations);
  const routesRef = useRef(routes);
  const highlightedEntitiesRef = useRef(highlightedEntities);

  // Dirty flags matrix to eliminate `setData` payload thrashing
  const dataDirtyRef = useRef({ threats: true, locations: true, routes: true });

  useEffect(() => {
    onLocationClickRef.current = onLocationClick;
    onThreatClickRef.current = onThreatClick;
    
    if (threats !== threatsRef.current) {
      threatsRef.current = threats;
      dataDirtyRef.current.threats = true;
    }
    if (locations !== locationsRef.current) {
      locationsRef.current = locations;
      dataDirtyRef.current.locations = true;
    }
    if (routes !== routesRef.current) {
      routesRef.current = routes;
      dataDirtyRef.current.routes = true;
    }
    if (highlightedEntities !== highlightedEntitiesRef.current) {
      highlightedEntitiesRef.current = highlightedEntities;
      dataDirtyRef.current.locations = true; 
    }
  }, [onLocationClick, onThreatClick, threats, locations, routes, highlightedEntities]);

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

    let animationId: number;

    map.on("style.load", () => {
      // ── Load Custom SVG Icons ───────────────────────────────────
      const loadIcon = (id: string, svg: string) => {
        const img = new Image(24, 24);
        img.onload = () => {
          if (!map.hasImage(id)) map.addImage(id, img);
        };
        img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
      };

      // High-fidelity node icons
      loadIcon("icon-warehouse", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M3 21V9l9-5 9 5v12H3Z" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M9 21v-5h6v5" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M6 13h12v3H6v-3Z" fill="none" stroke="#020617" stroke-width="1.5"/><line x1="10" y1="13" x2="10" y2="16" stroke="#020617" stroke-width="1.5"/><line x1="14" y1="13" x2="14" y2="16" stroke="#020617" stroke-width="1.5"/></svg>`);
      loadIcon("icon-supplier", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M6.5 2V17h13.5M6.5 6h10M6.5 10h10M6.5 14h10" fill="none" stroke="#020617" stroke-width="1.5"/><circle cx="16" cy="21" r="1.5" fill="none" stroke="#020617" stroke-width="1.5"/><circle cx="8" cy="21" r="1.5" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M6.5 17A2.5 2.5 0 0 1 4 14.5V2" fill="none" stroke="#020617" stroke-width="1.5"/></svg>`);
      loadIcon("icon-distribution_center", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2 12l10-7 10 7v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-9Z" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M8 21v-6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v6" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M12 10V6" fill="none" stroke="#020617" stroke-width="1.5"/><circle cx="12" cy="11" r="1" fill="#020617"/></svg>`);
      loadIcon("icon-port", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 21.5V4.5" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/><circle cx="12" cy="4.5" r="2" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M12 21.5a6 6 0 0 1-6-6v-3h12v3a6 6 0 0 1-6 6Z" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M6 12.5M18 12.5v-2" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M12 4.5l3 3m-6 0l3-3" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/><path d="M2 19.5c2 1 4 0 5-1 1-1 3-2 5 0 2 1.5 4 0 5-1 1-1 3-2 5 0" fill="none" stroke="#020617" stroke-width="1.5"/></svg>`);

      // Threat icons (High-Fidelity)
      loadIcon("icon-threat-hurricane", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 21.5c-4 0-7.7-2.3-9-6 .5 1.5 2 2.5 3.5 2.5 2.8 0 5-2.2 5-5 0-1.8 1-3.3 2.5-4 1.3-.6 3-.2 3.8 1 .8 1.2.6 2.8-.5 3.8-1 1-2.5 1.2-3.8.5-.7-.4-1.2-1-1.4-1.8M12 2.5c4 0 7.7 2.3 9 6-.5-1.5-2-2.5-3.5-2.5-2.8 0-5 2.2-5 5 0 1.8-1 3.3-2.5 4-1.3.6-3 .2-3.8-1-.8-1.2-.6-2.8.5-3.8 1-1 2.5-1.2 3.8-.5.7.4 1.2 1 1.4 1.8" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.5" fill="none" stroke="#020617" stroke-width="1.5"/><circle cx="12" cy="12" r="1.5" fill="#020617"/></svg>`);
      loadIcon("icon-threat-tornado", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M3 4h18M5 8h14M7 12h10M9 16h6M11 20h2" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/><path d="M4 6h16M6 10h12M8 14h8M10 18h4" fill="none" stroke="#020617" stroke-width="0.8" stroke-linecap="round"/><path d="M12 6c-2 2-3 4-3 6m6-6c2 2 3 4 3 6M10 14c-1 1-1.5 2-1.5 3m6-3c1 1 1.5 2 1.5 3" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
      loadIcon("icon-threat-flood", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2 13c3 0 3-3 6-3s3 3 6 3 3-3 6-3v7H2v-4z" fill="none" stroke="#020617" stroke-width="1.5" stroke-linejoin="round"/><path d="M2 17c3 0 3-3 6-3s3 3 6 3 3-3 6-3" fill="none" stroke="#020617" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 2C7 6.5 7 9.5 7 11.5c0 2.8 2.2 5 5 5s5-2.2 5-5c0-2-3-5-5-9.5z" fill="none" stroke="#020617" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 6.5c-1 1.5-1.5 3-1.5 4" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/></svg>`);
      loadIcon("icon-threat-winter_storm", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M4.93 19.07L19.07 4.93" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/><path d="M10 4l2 2 2-2M10 20l2-2 2 2M4 10l2 2-2 2M20 10l-2 2 2 2M6 6l2.5 1.5L7.5 10M18 18l-2.5-1.5L16.5 14M6 18l1.5-2.5L10 16.5M18 6l-1.5 2.5L14 7.5" fill="none" stroke="#020617" stroke-width="1.5" stroke-linejoin="round"/><circle cx="12" cy="12" r="1.5" fill="#020617"/></svg>`);
      loadIcon("icon-threat-severe_thunderstorm", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M11.5 2L3 13.5h7.5l-2 8.5L19 10.5h-7.5l2-8.5H11.5z" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 5L6 12h5l-1 5" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M6 6l-3 2M20 7l3-1M5 20l-3-2M21 18l-3 2" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/></svg>`);
      loadIcon("icon-threat-heat_wave", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" fill="none" stroke="#020617" stroke-width="1.5"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/><circle cx="12" cy="12" r="4.5" fill="none" stroke="#020617" stroke-width="1.5" stroke-dasharray="2 2"/></svg>`);
      loadIcon("icon-threat-wildfire", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2c-1.5 3.5-5 5.5-5 10s3 8 5 8 5-3.5 5-8-3.5-6.5-5-10v0Z" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 12c-1 2-2 3-2 5 0 2 1.5 3 2 3s2-1 2-3c0-2-1-3-2-5v0Z" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M18 10c0 0 4 3 4 7 0 3-2 4-4 4" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/><path d="M6 10c0 0-4 3-4 7 0 3 2 4 4 4" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round"/></svg>`);
      loadIcon("icon-threat-unknown", `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M10.3 3.9l-8.5 14.1a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" fill="none" stroke="#020617" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 8v5M12 16v1" fill="none" stroke="#020617" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="12" r="10" fill="none" stroke="#020617" stroke-width="1.5" stroke-dasharray="2 4"/></svg>`);

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

      map.addLayer({
        id: "threat-icons",
        type: "symbol",
        source: "threat-centroids",
        layout: {
          "icon-image": ["concat", "icon-threat-", ["get", "event_type"]],
          "icon-size": [
            "interpolate", ["linear"], ["zoom"],
            3, 0.45,
            8, 0.7,
          ],
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
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
          const geom = e.features[0].geometry as GeoJSON.Point;
          if (onLocationClickRef.current && props && geom?.coordinates) {
            const loc = {
              ...props,
              coordinates: { lon: geom.coordinates[0], lat: geom.coordinates[1] }
            } as unknown as ERPLocation;
            onLocationClickRef.current(loc);
          }
        });
      });

      ["threat-fills", "threat-icons"].forEach(layer => {
        map.on("click", layer, (e) => {
          if (!e.features?.[0]) return;
          const props = e.features[0].properties;
          if (onThreatClickRef.current && props?.threat_id) {
            const fullThreat = threatsRef.current.find(t => t.threat_id === props.threat_id);
            if (fullThreat) {
              onThreatClickRef.current(fullThreat);
            }
          }
        });
      });

      // Cursor changes
      ["erp-points", "erp-icons", "threat-fills", "threat-icons"].forEach(layer => {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
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
      function animate() {
        if (!map || !map.isStyleLoaded() || !initializedRef.current) return;
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
      
      setStyleLoaded(true);
    });

    map.addControl(new mapboxgl.NavigationControl(), "bottom-right");

    mapRef.current = map;

    return () => {
      cancelAnimationFrame(animationId);
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

    const features: GeoJSON.Feature[] = threatsRef.current.map((t) => ({
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

    const centroidFeatures: GeoJSON.Feature[] = threatsRef.current
      .filter((t) => t.centroid)
      .map((t) => ({
        type: "Feature",
        properties: {
          threat_id: t.threat_id,
          severity: t.severity,
          event_type: t.event_type || "unknown",
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

    const features: GeoJSON.Feature[] = locationsRef.current.map((loc) => ({
      type: "Feature",
      properties: {
        location_id: loc.location_id,
        name: loc.name,
        type: loc.type,
        reliability_index: loc.reliability_index,
        inventory_value_usd: loc.inventory_value_usd,
        avg_lead_time_hours: loc.avg_lead_time_hours,
        color: LOCATION_COLORS[loc.type] || "#6b7280",
        highlighted: highlightedEntitiesRef.current.includes(loc.location_id) || highlightedEntitiesRef.current.includes(loc.name),
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

    for (const route of routesRef.current) {
      const origin = locationsRef.current.find((l) => l.location_id === route.original_supplier_id);
      const dest   = locationsRef.current.find((l) => l.location_id === route.proposed_supplier_id);
      if (!origin || !dest) continue;

      // Prefer the real Mapbox road geometry stored on the proposal.
      // Fall back to a turf great-circle arc which looks far better than a
      // two-point straight line on a 3-D globe projection.
      let lineGeometry: GeoJSON.Geometry;
      if (route.route_geometry) {
        lineGeometry = route.route_geometry;
      } else if (origin.coordinates.lon === dest.coordinates.lon && origin.coordinates.lat === dest.coordinates.lat) {
        lineGeometry = {
          type: "LineString",
          coordinates: [
            [origin.coordinates.lon, origin.coordinates.lat],
            [dest.coordinates.lon, dest.coordinates.lat]
          ],
        };
      } else {
        try {
          const arc = turf.greatCircle(
            turf.point([origin.coordinates.lon, origin.coordinates.lat]),
            turf.point([dest.coordinates.lon,   dest.coordinates.lat]),
            { npoints: 100 },
          );
          lineGeometry = arc.geometry;
        } catch (err) {
          console.warn("[AegisGlobe] turf.greatCircle failed, falling back to LineString.", err);
          lineGeometry = {
            type: "LineString",
            coordinates: [
              [origin.coordinates.lon, origin.coordinates.lat],
              [dest.coordinates.lon, dest.coordinates.lat]
            ]
          };
        }
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

  // ── Sync data to map continuously using optimized dirty-checking ──
  // By tracking dirty states with refs and using a lightweight interval,
  // we decouple React renders from WebGL data updates.
  // This guarantees map sources will be populated safely with 0 dropped frames.
  useEffect(() => {
    const interval = setInterval(() => {
      const map = mapRef.current;
      if (!map || !styleLoaded || !map.isStyleLoaded()) return;

      let allSourcesReady = true;
      for (const id of ["threats", "threat-centroids", "erp-locations", "routes"]) {
        if (!map.getSource(id)) {
          allSourcesReady = false;
          break;
        }
      }

      if (allSourcesReady) {
        if (dataDirtyRef.current.threats) {
          updateThreats();
          dataDirtyRef.current.threats = false;
        }
        if (dataDirtyRef.current.locations) {
          updateLocations();
          dataDirtyRef.current.locations = false;
        }
        if (dataDirtyRef.current.routes) {
          updateRoutes();
          dataDirtyRef.current.routes = false;
        }
      }
    }, 100);

    return () => clearInterval(interval);
  }, [styleLoaded]);

  // ── Make sure painting reacts to selectedThreatId changes ─────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!styleLoaded) return;

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

    // Move camera only when the actual selected ID changes (not on polling data refresh)
    if (selectedThreatId && selectedThreatId !== previousThreatIdRef.current) {
      previousThreatIdRef.current = selectedThreatId;
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
  }, [selectedThreatId, threats, styleLoaded]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", position: "absolute", top: 0, left: 0 }}
    />
  );
}
