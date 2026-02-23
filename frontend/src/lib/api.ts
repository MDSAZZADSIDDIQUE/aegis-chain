const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  contextThreatId?: string
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      context_threat_id: contextThreatId ?? null,
    }),
  });
  if (!res.ok) throw new Error(`Chat request failed: ${res.status}`);
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
