"use client";

import { useEffect, useState, useCallback, useRef, type FormEvent } from "react";
import dynamic from "next/dynamic";
import ChatToMap from "@/components/chat/ChatToMap";
import GlobeErrorBoundary from "@/components/map/GlobeErrorBoundary";
import PipelineTelemetry from "@/components/dashboard/PipelineTelemetry";
import RLOverlay from "@/components/dashboard/RLOverlay";
import {
  fetchDashboardState,
  triggerPipeline,
  triggerIngest,
  subscribeToEvents,
  subscribePipelineProgress,
  createERPLocation,
  type DashboardState,
  type WeatherThreat,
  type ERPLocation,
  type ERPLocationUpsert,
  type PipelineProgressEvent,
  type Proposal,
} from "@/lib/api";

const AegisGlobe = dynamic(() => import("@/components/map/AegisGlobe"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center bg-stone-950">
      <span className="font-mono text-xs text-stone-600 tracking-widest uppercase">
        INITIALIZING SATELLITE FEED...
      </span>
    </div>
  ),
});

// SSE handles real-time pushes; this is the last-resort fallback interval
const POLL_MS = 300_000; // 5 minutes

// Severity → hazard color token
const SEV_COLOR: Record<string, string> = {
  extreme: "#dc2626",
  severe:  "#ea580c",
  moderate:"#d97706",
  minor:   "#ca8a04",
  unknown: "#78716c",
};

// Event type → short code for dense display
const EVENT_CODE: Record<string, string> = {
  hurricane:          "HUR",
  tornado:            "TOR",
  flood:              "FLD",
  winter_storm:       "WNT",
  severe_thunderstorm:"TST",
  heat_wave:          "HEW",
  wildfire:           "WFR",
  unknown:            "UNK",
};

export default function DashboardPage() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [highlighted, setHighlighted] = useState<string[]>([]);
  const [selectedThreat, setSelectedThreat] = useState<WeatherThreat | null>(null);
  const [selectedRoute, setSelectedRoute] = useState<Proposal | null>(null);
  const [running, setRunning] = useState<"idle" | "ingest" | "pipeline">("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [pipelineMetrics, setPipelineMetrics] = useState({ approved: 0, hitl: 0 });

  const stateRef = useRef<DashboardState | null>(null);

  const loadState = useCallback(async () => {
    try {
      const data = await fetchDashboardState();
      setState(data);
      stateRef.current = data;
      setLastSync(new Date());
      setError(null);
    } catch {
      setError("SYS:DISCONNECTED — backend offline");
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    loadState();

    // SSE real-time push — reload dashboard on any backend event
    const closeSSE = subscribeToEvents(
      () => loadState(),
      () => { /* connection errors are normal during backend restart — ignore */ }
    );

    // Pipeline progress WebSocket for granular HUD updates
    const closeWS = subscribePipelineProgress((ev: PipelineProgressEvent) => {
      if (ev.agent === "auditor" && ev.status === "complete") {
        setPipelineMetrics({
          approved: ev.approved ?? 0,
          hitl: ev.hitl ?? 0,
        });
        // Immediately refresh state to pull the new arcs
        loadState();
      }
    });

    // 5-minute fallback poll in case SSE drops silently
    const interval = setInterval(loadState, POLL_MS);

    return () => {
      closeSSE();
      closeWS();
      clearInterval(interval);
    };
  }, [loadState]);

  const handleIngest = async () => {
    setRunning("ingest");
    try { await triggerIngest(); await loadState(); }
    catch { setError("INGEST:FAILED"); }
    setRunning("idle");
  };

  const handlePipeline = async () => {
    setRunning("pipeline");
    try { await triggerPipeline(); await loadState(); }
    catch { setError("PIPELINE:FAILED"); }
    setRunning("idle");
  };

  const handleLocationClick = useCallback((loc: ERPLocation) => setHighlighted([loc.location_id]), []);
  const handleThreatClick = useCallback((threat: WeatherThreat) => {
    setSelectedThreat(threat);
    setSelectedRoute(null);
  }, []);


  const var_millions = ((state?.total_value_at_risk ?? 0) / 1_000_000).toFixed(2);
  const reroutes_count = (state?.active_routes.length ?? 0) + pipelineMetrics.approved;
  const has_pending = (state?.pending_proposals.length ?? 0) > 0 || pipelineMetrics.hitl > 0;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-stone-950 text-stone-200">

      {/* ══════════════════════════════════════════════════════
          LEFT PANEL — Threat Intelligence
      ══════════════════════════════════════════════════════ */}
      <aside className="flex flex-col w-[300px] shrink-0 bg-stone-900 border-r border-stone-800 overflow-hidden">

        {/* ── Wordmark ─────────────────────────────────────── */}
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-stone-800">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
            <polygon points="10,2 18,7 18,13 10,18 2,13 2,7" stroke="#a3e635" strokeWidth="1.5" fill="none"/>
            <circle cx="10" cy="10" r="2.5" fill="#a3e635"/>
          </svg>
          <div>
            <div className="font-mono text-sm font-semibold tracking-tight text-stone-100">
              AEGIS<span className="text-lime-400">//</span>CHAIN
            </div>
            <div className="tac-label">CLIMATE-RESILIENT AGRI SUPPLY ERP</div>
          </div>
        </div>

        {/* ── System status strip ───────────────────────────── */}
        <div className="flex items-center gap-3 px-4 py-2 bg-stone-950 border-b border-stone-800">
          <span className="flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: error ? "#dc2626" : "#a3e635",
                       boxShadow: error ? "0 0 4px #dc2626" : "0 0 4px #a3e635" }}
            />
            <span className="font-mono text-[9px] uppercase tracking-widest text-stone-500">
              {error ? "OFFLINE" : "LIVE"}
            </span>
          </span>
          <span className="font-mono text-[9px] text-stone-600">
            {lastSync ? lastSync.toLocaleTimeString([], { hour12: false }) : "--:--:--"}
          </span>
          {error && (
            <span className="font-mono text-[9px] text-red-500 truncate">{error}</span>
          )}
        </div>

        {/* ── KPI row ───────────────────────────────────────── */}
        <div className="grid grid-cols-4 border-b border-stone-800">
          <Kpi label="THREATS" value={state?.active_threats.length ?? "—"} accent="text-red-500" />
          <Kpi label="NODES"   value={state?.erp_locations.length  ?? "—"} accent="text-lime-400" />
          <Kpi label="VAR $M"  value={var_millions}                         accent="text-orange-500" />
          <Kpi label="ROUTES"  value={state?.active_routes.length  ?? "—"} accent="text-lime-400" />
        </div>

        {/* ── Operations ────────────────────────────────────── */}
        <div className="flex gap-1.5 px-3 py-2 border-b border-stone-800">
          <button
            onClick={handleIngest}
            disabled={running !== "idle"}
            className="tac-btn flex-1"
          >
            {running === "ingest" ? "▶ POLLING..." : "↓ POLL NOAA/FIRMS"}
          </button>
          <button
            onClick={handlePipeline}
            disabled={running !== "idle"}
            className="tac-btn-lime flex-1"
          >
            {running === "pipeline" ? "▶ RUNNING..." : "▲ RUN AGENTS"}
          </button>
        </div>

        {/* ── Add ERP Node ──────────────────────────────────── */}
        <AddNodePanel onSuccess={loadState} />

        {/* ── Active threat log ────────────────────────────── */}
        <SectionHeader label="ACTIVE THREAT EVENTS" count={state?.active_threats.length} />

        <div className="flex-1 min-h-[300px] overflow-y-auto">
          {state?.active_threats.length === 0 && (
            <div className="px-4 py-3 font-mono text-[10px] text-stone-600">
              NO ACTIVE EVENTS DETECTED
            </div>
          )}

          {state?.active_threats.slice(0, 20).map((t) => (
            <button
              key={t.threat_id}
              onClick={() => handleThreatClick(t)}
              className="w-full text-left border-b border-stone-800 last:border-b-0 hover:bg-stone-800 transition-colors duration-75"
              style={{
                background: selectedThreat?.threat_id === t.threat_id
                  ? "#292524"
                  : "transparent",
                borderLeft: `2px solid ${SEV_COLOR[t.severity] ?? SEV_COLOR.unknown}`,
              }}
            >
              <div className="px-3 py-2">
                {/* Row 1: code + severity badge + time */}
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="font-mono text-[10px] font-bold text-stone-300">
                    {EVENT_CODE[t.event_type] ?? "UNK"}
                  </span>
                  <span
                    className="font-mono text-[8px] uppercase px-1 py-px"
                    style={{ background: SEV_COLOR[t.severity] ?? SEV_COLOR.unknown, color: "#0c0a09", borderRadius: "1px" }}
                  >
                    {t.severity || "unknown"}
                  </span>
                  <span className="font-mono text-[9px] text-stone-600 ml-auto">
                    {new Date(t.ingested_at).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
                {/* Row 2: headline */}
                <div className="font-mono text-[10px] text-stone-400 truncate leading-tight">
                  {t.headline || t.description?.slice(0, 72) || "No description"}
                </div>
                {/* Row 3: source + ID */}
                <div className="flex gap-2 mt-0.5">
                  <span className="tac-label">{t.source.toUpperCase()}</span>
                  <span className="tac-label truncate">{t.threat_id.slice(0, 24)}</span>
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* ── HITL pending proposals ────────────────────────── */}
        {state?.pending_proposals && state.pending_proposals.length > 0 && (
          <>
            <SectionHeader label="AWAITING APPROVAL" count={state.pending_proposals.length} accent="text-amber-500" />
            <div className="overflow-y-auto max-h-[30vh]">
              {state.pending_proposals.map((p) => (
                <button
                  key={p.proposal_id}
                  onClick={() => { setSelectedRoute(p); setSelectedThreat(null); }}
                  className="w-full text-left px-3 py-2 border-b border-stone-800 hover:bg-stone-800 transition-colors"
                  style={{ 
                    borderLeft: "2px solid #f59e0b",
                    background: selectedRoute?.proposal_id === p.proposal_id ? "#292524" : "transparent"
                  }}
                >
                  <div className="flex items-baseline gap-1.5 mb-0.5">
                    <span className="font-mono text-[10px] font-bold text-amber-400">HITL</span>
                    <span className="font-mono text-[9px] text-stone-400 truncate">{p.proposed_supplier_name}</span>
                  </div>
                  <div className="flex gap-3">
                    <MetaPair label="COST" value={`$${p.reroute_cost_usd.toLocaleString()}`} />
                    <MetaPair label="SCORE" value={p.attention_score.toFixed(4)} />
                  </div>
                </button>
              ))}
            </div>
          </>
        )}

        {/* ── Legend ─────────────────────────────────────────── */}
        <div className="px-3 py-2 border-t border-stone-800 bg-stone-950">
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            {[
              { color: "#a3e635", label: "SUPPLIER" },
              { color: "#4ade80", label: "WAREHOUSE" },
              { color: "#34d399", label: "DIST CENTER" },
              { color: "#a3e635", label: "PORT" },
            ].map((l) => (
              <div key={l.label} className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: l.color }} />
                <span className="tac-label">{l.label}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ══════════════════════════════════════════════════════
          CENTER — Satellite Map
      ══════════════════════════════════════════════════════ */}
      <main className="relative flex-1 bg-stone-950">
        <GlobeErrorBoundary>
          <AegisGlobe
            threats={state?.active_threats ?? []}
            locations={state?.erp_locations ?? []}
            routes={state?.active_routes ?? []}
            highlightedEntities={highlighted}
            selectedThreatId={selectedThreat?.threat_id}
            onLocationClick={handleLocationClick}
            onThreatClick={handleThreatClick}
          />
        </GlobeErrorBoundary>
        
        {/* Top UI Elements */}
        <PipelineTelemetry />
        <RLOverlay proposal={selectedRoute} onClose={() => setSelectedRoute(null)} />

        {/* ── Bottom-left HUD strip ─────────────────────────── */}
        <div
          className="absolute bottom-5 left-4 flex items-center gap-3 px-3 py-1.5 border border-stone-700"
          style={{ background: "rgba(28,25,23,0.88)", backdropFilter: "blur(6px)", borderRadius: "2px" }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: error ? "#dc2626" : (has_pending ? "#f59e0b" : "#a3e635"),
              boxShadow: error ? "0 0 5px #dc2626" : (has_pending ? "0 0 5px #f59e0b" : "0 0 5px #a3e635"),
            }}
          />
          <span className="font-mono text-[10px] text-stone-400 uppercase tracking-wider">
            {error ? "DISCONNECTED" : (has_pending ? "AWAITING APPROVAL" : "SATELLITE FEED LIVE")}
          </span>
          <span className="w-px h-3 bg-stone-700" />
          <span className="font-mono text-[10px] text-stone-500">
            {state?.active_threats.length ?? 0} EVENTS
          </span>
          <span className="w-px h-3 bg-stone-700" />
          <span className="font-mono text-[10px] text-orange-500">
            ${var_millions}M VAR
          </span>
          <span className="w-px h-3 bg-stone-700" />
          <span className="font-mono text-[10px] text-lime-400">
            {reroutes_count} REROUTES PREVENTED
          </span>
        </div>

        {/* ── Selected threat detail overlay ────────────────── */}
        {selectedThreat && (
          <div
            className="absolute top-4 left-1/2 -translate-x-1/2 px-4 py-2 border border-stone-700 flex items-center gap-4"
            style={{ background: "rgba(28,25,23,0.92)", backdropFilter: "blur(6px)", borderRadius: "2px" }}
          >
            <span
              className="font-mono text-[10px] font-bold uppercase"
              style={{ color: SEV_COLOR[selectedThreat.severity] }}
            >
              {EVENT_CODE[selectedThreat.event_type]} / {selectedThreat.severity.toUpperCase()}
            </span>
            <span className="w-px h-3 bg-stone-700" />
            <span className="font-mono text-[10px] text-stone-300 max-w-xs truncate">
              {selectedThreat.headline || selectedThreat.description?.slice(0, 80)}
            </span>
            <button
              onClick={() => setSelectedThreat(null)}
              className="font-mono text-[10px] text-stone-600 hover:text-stone-300 ml-2"
            >
              ✕
            </button>
          </div>
        )}
      </main>

      {/* ══════════════════════════════════════════════════════
          RIGHT PANEL — Auditor Command Log
      ══════════════════════════════════════════════════════ */}
      <aside className="flex flex-col w-[380px] shrink-0 border-l border-stone-800">
        <ChatToMap
          contextThreatId={selectedThreat?.threat_id}
          onHighlight={setHighlighted}
        />
      </aside>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────

function Kpi({
  label,
  value,
  accent = "text-lime-400",
}: {
  label: string;
  value: string | number;
  accent?: string;
}) {
  return (
    <div className="flex flex-col gap-0 px-3 py-2 border-r border-stone-800 last:border-r-0">
      <span className="tac-label">{label}</span>
      <span className={`font-mono text-base font-bold leading-tight ${accent}`}>
        {value}
      </span>
    </div>
  );
}

function SectionHeader({
  label,
  count,
  accent = "text-stone-500",
}: {
  label: string;
  count?: number;
  accent?: string;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 bg-stone-950 border-t border-b border-stone-800">
      <span className="tac-label">{label}</span>
      {count !== undefined && (
        <span className={`font-mono text-[9px] font-bold ${accent}`}>{count}</span>
      )}
    </div>
  );
}

function MetaPair({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="tac-label">{label}</span>
      <span className="font-mono text-[10px] text-lime-400">{value}</span>
    </span>
  );
}

// ── AddNodePanel ───────────────────────────────────────────────────────────
// Compact collapsible form for registering a new ERP node from the sidebar.

const NODE_TYPES: ERPLocationUpsert["type"][] = [
  "supplier",
  "warehouse",
  "distribution_center",
  "port",
];
const NODE_TYPE_LABEL: Record<ERPLocationUpsert["type"], string> = {
  supplier:             "SUPPLIER",
  warehouse:            "WAREHOUSE",
  distribution_center:  "DIST CENTER",
  port:                 "PORT",
};

const INPUT_CLS =
  "font-mono text-[10px] bg-stone-900 border border-stone-700 text-stone-200 " +
  "px-2 py-1 w-full focus:outline-none focus:border-lime-600 placeholder-stone-600";

function TacField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="tac-label">{label}</span>
      {children}
    </label>
  );
}

function AddNodePanel({ onSuccess }: { onSuccess: () => void }) {
  const [open, setOpen]           = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback]   = useState<{ ok: boolean; msg: string } | null>(null);

  // form state
  const [name, setName]       = useState("");
  const [type, setType]       = useState<ERPLocationUpsert["type"]>("supplier");
  const [lat, setLat]         = useState("");
  const [lon, setLon]         = useState("");
  const [inv, setInv]         = useState("");
  const [leadTime, setLeadTime] = useState("");

  const reset = () => {
    setName(""); setLat(""); setLon(""); setInv(""); setLeadTime("");
    setType("supplier"); setFeedback(null);
  };

  const handleToggle = () => {
    setOpen((o) => !o);
    if (open) reset();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFeedback(null);
    try {
      const payload: ERPLocationUpsert = {
        name: name.trim(),
        type,
        lat:  parseFloat(lat),
        lon:  parseFloat(lon),
        ...(inv      ? { inventory_value_usd:  parseFloat(inv) }      : {}),
        ...(leadTime ? { avg_lead_time_hours:  parseFloat(leadTime) } : {}),
      };
      const res = await createERPLocation(payload);
      setFeedback({ ok: true, msg: `${res.status.toUpperCase()} · ${res.location_id}` });
      onSuccess();
      setTimeout(() => { reset(); setOpen(false); }, 2200);
    } catch {
      setFeedback({ ok: false, msg: "ERR: SUBMISSION FAILED" });
    }
    setSubmitting(false);
  };

  return (
    <div className="border-b border-stone-800">
      {/* Toggle */}
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-stone-800 transition-colors duration-75"
      >
        <span
          className="font-mono text-[9px] text-lime-400"
          style={{ lineHeight: 1 }}
        >
          {open ? "✕" : "⊕"}
        </span>
        <span className="tac-label">{open ? "CANCEL" : "ADD ERP NODE"}</span>
      </button>

      {/* Form */}
      {open && (
        <form
          onSubmit={handleSubmit}
          className="px-3 py-2 bg-stone-950 flex flex-col gap-2"
        >
          <TacField label="NAME *">
            <input
              required
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="APEX GRAIN CO."
              className={INPUT_CLS}
              style={{ borderRadius: "1px" }}
            />
          </TacField>

          <TacField label="TYPE">
            <select
              value={type}
              onChange={(e) => setType(e.target.value as ERPLocationUpsert["type"])}
              className={INPUT_CLS}
              style={{ borderRadius: "1px" }}
            >
              {NODE_TYPES.map((t) => (
                <option key={t} value={t}>{NODE_TYPE_LABEL[t]}</option>
              ))}
            </select>
          </TacField>

          {/* Lat / Lon side by side */}
          <div className="flex gap-1.5">
            <TacField label="LAT *">
              <input
                required
                type="number"
                step="any"
                min={-90}
                max={90}
                value={lat}
                onChange={(e) => setLat(e.target.value)}
                placeholder="38.90"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
            <TacField label="LON *">
              <input
                required
                type="number"
                step="any"
                min={-180}
                max={180}
                value={lon}
                onChange={(e) => setLon(e.target.value)}
                placeholder="-77.03"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
          </div>

          {/* Optional fields */}
          <div className="flex gap-1.5">
            <TacField label="INV $">
              <input
                type="number"
                step="any"
                min={0}
                value={inv}
                onChange={(e) => setInv(e.target.value)}
                placeholder="optional"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
            <TacField label="LEAD HRS">
              <input
                type="number"
                step="any"
                min={0}
                value={leadTime}
                onChange={(e) => setLeadTime(e.target.value)}
                placeholder="24"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
          </div>

          {/* Feedback line */}
          {feedback && (
            <span
              className={`font-mono text-[9px] uppercase tracking-widest truncate ${
                feedback.ok ? "text-lime-400" : "text-red-500"
              }`}
            >
              {feedback.msg}
            </span>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="tac-btn-lime"
          >
            {submitting ? "▶ REGISTERING..." : "↑ REGISTER NODE"}
          </button>
        </form>
      )}
    </div>
  );
}
