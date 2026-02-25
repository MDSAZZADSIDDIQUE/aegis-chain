const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// WebSocket base URL — same host, swap protocol
const WS_URL  = API_URL.replace(/^http/, "ws");

export interface WeatherThreat {
  threat_id: string;
  source: string;
  event_type: string;
  severity: string;
  headline: string;
  description: string;
  affected_zone: GeoJSON.Geometry;
  centroid: { lat: number; lon: number } | null;
  effective: string | null;
  expires: string | null;
  status: string;
  confidence_pct: number | null;
  frp_mw: number | null;
  ingested_at: string;
}

export interface ERPLocation {
  location_id: string;
  name: string;
  type: string;
  coordinates: { lat: number; lon: number };
  inventory_value_usd: number;
  reliability_index: number;
  avg_lead_time_hours: number;
  active: boolean;
  tags?: string[];
}

export interface Proposal {
  proposal_id: string;
  threat_id: string;
  original_supplier_id: string;
  proposed_supplier_id: string;
  proposed_supplier_name: string;
  attention_score: number;
  mapbox_drive_time_minutes: number;
  mapbox_distance_km: number;
  reroute_cost_usd: number;
  rationale: string;
  hitl_status?: string;
  approved?: boolean;
  /** GeoJSON LineString from Mapbox Directions — null when routing failed. */
  route_geometry?: GeoJSON.Geometry | null;
}

export interface DashboardState {
  active_threats: WeatherThreat[];
  erp_locations: ERPLocation[];
  active_routes: Proposal[];
  pending_proposals: Proposal[];
  total_value_at_risk: number;
}

export interface ChatResponse {
  answer: string;
  esql_query: string | null;
  highlighted_entities: string[];
  map_annotations: Array<{ type: string; [key: string]: unknown }>;
}

export async function fetchDashboardState(): Promise<DashboardState> {
  const res = await fetch(`${API_URL}/dashboard/state`);
  if (!res.ok) throw new Error(`Dashboard fetch failed: ${res.status}`);
  return res.json();
}

export async function sendChatMessage(
  question: string,
  contextThreatId?: string,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      context_threat_id: contextThreatId ?? null,
    }),
    signal,
  });
  if (!res.ok) throw new Error(`Chat request failed: ${res.status}`);
  return res.json();
}

export interface ERPLocationUpsert {
  name: string;
  type: "supplier" | "warehouse" | "distribution_center" | "port";
  lat: number;
  lon: number;
  location_id?: string;
  inventory_value_usd?: number;
  reliability_index?: number;
  avg_lead_time_hours?: number;
  contract_sla?: string;
  capacity_units?: number;
  active?: boolean;
  tags?: string[];
  region?: string;
  country_code?: string;
  address?: string;
}

export async function createERPLocation(
  data: ERPLocationUpsert
): Promise<{ status: string; location_id: string }> {
  const res = await fetch(`${API_URL}/erp-locations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Create ERP location failed: ${res.status}`);
  return res.json();
}

export async function triggerPipeline(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/pipeline/run`, { method: "POST" });
  if (!res.ok) throw new Error(`Pipeline trigger failed: ${res.status}`);
  return res.json();
}

export async function triggerIngest(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/ingest/poll`, { method: "POST" });
  if (!res.ok) throw new Error(`Ingest trigger failed: ${res.status}`);
  return res.json();
}

// ── WebSocket: pipeline progress ─────────────────────────────────────────────

export interface PipelineProgressEvent {
  /** "watcher" | "procurement" | "auditor" | "pipeline" */
  agent: string;
  /** "running" | "complete" */
  status: string;
  // Watcher complete fields
  threats?: number;
  at_risk?: number;
  bottlenecks?: number;
  var_usd?: number;
  // Procurement fields
  correlations?: number;
  proposals?: number;
  // Auditor complete fields
  approved?: number;
  hitl?: number;
  rejected?: number;
  // Pipeline complete fields
  actions?: number;
  reason?: string;
}

/**
 * Open a WebSocket to /ws/pipeline and forward progress events.
 * Returns a cleanup function — call it on component unmount.
 *
 * @param onEvent  Called for every progress event (ping frames are filtered).
 * @param onClose  Optional; called when the connection closes.
 */
export function subscribePipelineProgress(
  onEvent: (event: PipelineProgressEvent) => void,
  onClose?: () => void,
): () => void {
  const ws = new WebSocket(`${WS_URL}/ws/pipeline`);

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as Record<string, unknown>;
      // Filter out server keepalive pings
      if (data.type === "ping") return;
      onEvent(data as unknown as PipelineProgressEvent);
    } catch {
      // malformed frame — ignore
    }
  };

  if (onClose) ws.onclose = onClose;

  return () => ws.close();
}

// ── Server-Sent Events ────────────────────────────────────────────────────────

export type AegisEventType =
  | "connected"
  | "ingest_complete"
  | "pipeline_complete"
  | "execution_event";

export interface AegisEvent {
  type: AegisEventType;
  data: Record<string, unknown>;
}

/**
 * Subscribe to the backend SSE stream.
 * Returns a cleanup function — call it on component unmount.
 *
 * @param onEvent  Called for every named event received.
 * @param onError  Optional; called when the EventSource fires an error.
 */
export function subscribeToEvents(
  onEvent: (event: AegisEvent) => void,
  onError?: (err: Event) => void
): () => void {
  const es = new EventSource(`${API_URL}/events`);

  const handle = (raw: MessageEvent) => {
    try {
      const data: Record<string, unknown> = JSON.parse(raw.data);
      onEvent({ type: raw.type as AegisEventType, data });
    } catch {
      // malformed JSON — ignore
    }
  };

  const eventTypes: AegisEventType[] = [
    "connected",
    "ingest_complete",
    "pipeline_complete",
    "execution_event",
  ];
  for (const t of eventTypes) {
    es.addEventListener(t, handle as EventListener);
  }

  if (onError) {
    es.addEventListener("error", onError);
  }

  return () => es.close();
}
