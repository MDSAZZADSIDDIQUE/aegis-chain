import { Dispatch, SetStateAction, useState } from "react";
import AddNodePanel from "./AddNodePanel";
import type { WeatherThreat, DashboardState, Proposal } from "@/lib/api";

const SEV_COLOR: Record<string, string> = {
  extreme: "#dc2626",
  severe: "#ea580c",
  moderate: "#d97706",
  minor: "#ca8a04",
  unknown: "#78716c",
};

const EVENT_CODE: Record<string, string> = {
  hurricane: "HUR",
  tornado: "TOR",
  flood: "FLD",
  winter_storm: "WNT",
  severe_thunderstorm: "TST",
  heat_wave: "HEW",
  wildfire: "WFR",
  unknown: "UNK",
};

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
    <div className="flex flex-col gap-0 px-3 py-3 last:border-r-0">
      <span className="tac-label mb-1">{label}</span>
      <span className={`font-mono text-xl font-bold leading-tight ${accent}`}>
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
    <div className="flex items-center justify-between px-3 py-2 bg-stone-950 border-b border-stone-800">
      <span className="tac-label">{label}</span>
      {count !== undefined && (
        <span className={`font-mono text-[10px] font-bold ${accent}`}>
          {count}
        </span>
      )}
    </div>
  );
}

function MetaPair({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="tac-label text-[8px]">{label}</span>
      <span className="font-mono text-[10px] font-bold text-stone-200">
        {value}
      </span>
    </div>
  );
}

interface ThreatPanelProps {
  state?: DashboardState;
  error: string | null;
  lastSync: Date | null;
  running: "idle" | "ingest" | "pipeline";
  pipelineMetrics: { approved: number; hitl: number };
  selectedThreat: WeatherThreat | null;
  selectedRoute: Proposal | null;
  handleIngest: () => void;
  handlePipeline: () => void;
  handleThreatClick: (threat: WeatherThreat) => void;
  setSelectedRoute: Dispatch<SetStateAction<Proposal | null>>;
  setSelectedThreat: Dispatch<SetStateAction<WeatherThreat | null>>;
  loadState: () => void;
  var_millions: string;
}

export default function ThreatPanel({
  state,
  error,
  lastSync,
  running,
  pipelineMetrics,
  selectedThreat,
  selectedRoute,
  handleIngest,
  handlePipeline,
  handleThreatClick,
  setSelectedRoute,
  setSelectedThreat,
  loadState,
  var_millions,
}: ThreatPanelProps) {
  const [activeTab, setActiveTab] = useState<"OVERVIEW" | "THREATS" | "APPROVALS">("OVERVIEW");

  const pendingCount = state?.pending_proposals?.length ?? 0;
  const threatCount = state?.active_threats?.length ?? 0;

  return (
    <aside className="flex flex-col w-[320px] lg:w-[350px] shrink-0 bg-stone-900 border-r border-stone-800 overflow-hidden z-10">
      {/* ── Wordmark ─────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-4 border-b border-stone-800 bg-stone-950">
        <svg width="24" height="24" viewBox="0 0 20 20" fill="none" aria-hidden>
          <polygon
            points="10,2 18,7 18,13 10,18 2,13 2,7"
            stroke="#a3e635"
            strokeWidth="1.5"
            fill="none"
          />
          <circle cx="10" cy="10" r="2.5" fill="#a3e635" />
        </svg>
        <div>
          <div className="font-mono text-base font-semibold tracking-tight text-stone-100 uppercase">
            Aegis<span className="text-lime-400">//</span>Chain
          </div>
          <div className="tac-label text-stone-500">CLIMATE-RESILIENT AGRI SUPPLY ERP</div>
        </div>
      </div>

      {/* ── System status strip ───────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2 bg-stone-900 border-b border-stone-800 shadow-sm">
        <span className="flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: error ? "#dc2626" : "#a3e635",
              boxShadow: error ? "0 0 4px #dc2626" : "0 0 4px #a3e635",
            }}
          />
          <span className="font-mono text-[9px] uppercase tracking-widest text-stone-400">
            {error ? "OFFLINE" : "LIVE SATELLITE FEED"}
          </span>
        </span>
        <span className="font-mono text-[9px] text-stone-600 ml-auto flex gap-1">
          <span>SYNC:</span>
          <span className="text-stone-400" suppressHydrationWarning>{lastSync ? lastSync.toLocaleTimeString([], { hour12: false }) : "--:--:--"}</span>
        </span>
      </div>
      
      {error && (
        <div className="px-4 py-1.5 bg-red-950/30 border-b border-red-900/50">
          <span className="font-mono text-[9px] text-red-500 truncate">
            {error}
          </span>
        </div>
      )}

      {/* ── Tabs ──────────────────────────────────────────── */}
      <div className="flex border-b border-stone-800 bg-stone-950 sticky top-0 z-20 shadow-sm">
        <button
          onClick={() => setActiveTab("OVERVIEW")}
          className={`flex-1 py-3 font-mono text-[10px] font-bold tracking-wider transition-colors border-b-2 ${
            activeTab === "OVERVIEW"
              ? "text-lime-400 border-lime-400 bg-stone-900"
              : "text-stone-500 border-transparent hover:text-stone-300 hover:bg-stone-900/50"
          }`}
        >
          OVERVIEW
        </button>
        <button
          onClick={() => setActiveTab("THREATS")}
          className={`flex-1 flex items-center justify-center gap-1.5 py-3 font-mono text-[10px] font-bold tracking-wider transition-colors border-b-2 ${
            activeTab === "THREATS"
              ? "text-red-400 border-red-400 bg-stone-900"
              : "text-stone-500 border-transparent hover:text-stone-300 hover:bg-stone-900/50"
          }`}
        >
          THREATS
          {threatCount > 0 && (
            <span className={`px-1.5 py-0.5 rounded-full text-[8px] leading-none ${activeTab === 'THREATS' ? 'bg-red-500/20 text-red-400' : 'bg-stone-800 text-stone-400'}`}>
              {threatCount}
            </span>
          )}
        </button>
        <button
          onClick={() => setActiveTab("APPROVALS")}
          className={`flex-1 flex items-center justify-center gap-1.5 py-3 font-mono text-[10px] font-bold tracking-wider transition-colors border-b-2 ${
            activeTab === "APPROVALS"
              ? "text-amber-400 border-amber-400 bg-stone-900"
              : "text-stone-500 border-transparent hover:text-stone-300 hover:bg-stone-900/50"
          }`}
        >
          APPROVALS
          {pendingCount > 0 && (
            <span className={`px-1.5 py-0.5 rounded-full text-[8px] leading-none ${activeTab === 'APPROVALS' ? 'bg-amber-500/20 text-amber-400' : 'bg-stone-800 text-stone-400'}`}>
              {pendingCount}
            </span>
          )}
        </button>
      </div>

      <div className="flex-1 flex flex-col overflow-hidden bg-stone-900">
        {activeTab === "OVERVIEW" && (
          <div className="flex flex-col h-full overflow-y-auto">
            {/* ── KPI row ───────────────────────────────────────── */}
            <div className="grid grid-cols-2 border-b border-stone-800 bg-stone-950/30">
              <div className="border-r border-b border-stone-800">
                <Kpi
                  label="ACTIVE THREATS"
                  value={state?.active_threats.length ?? "—"}
                  accent="text-red-500"
                />
              </div>
              <div className="border-b border-stone-800">
                <Kpi
                  label="INFRA NODES"
                  value={state?.erp_locations.length ?? "—"}
                  accent="text-lime-400"
                />
              </div>
              <div className="border-r border-stone-800">
                <Kpi label="VALUE AT RISK ($M)" value={var_millions} accent="text-orange-500" />
              </div>
              <div>
                <Kpi
                  label="ACTIVE REROUTES"
                  value={state?.active_routes.length ?? "—"}
                  accent="text-lime-400"
                />
              </div>
            </div>

            {/* ── Operations ────────────────────────────────────── */}
            <div className="flex flex-col gap-2 p-4 border-b border-stone-800">
              <div className="tac-label mb-1">MANUAL OPERATIONS</div>
              <button
                onClick={handleIngest}
                disabled={running !== "idle"}
                className="tac-btn w-full py-2.5 flex items-center justify-center gap-2"
              >
                {running === "ingest" ? "▶ POLLING DATA SOURCES..." : "↓ FORCE POLL NOAA / FIRMS"}
              </button>
              <button
                onClick={handlePipeline}
                disabled={running !== "idle"}
                className="tac-btn-lime w-full py-2.5 flex items-center justify-center gap-2"
              >
                {running === "pipeline" ? "▶ RUNNING AI AGENTS..." : "▲ RUN RESOLUTION PIPELINE"}
              </button>
            </div>

            {/* ── Add ERP Node ──────────────────────────────────── */}
            <AddNodePanel onSuccess={loadState} />

            <div className="flex-1 min-h-[40px]" />

            {/* ── Legend ─────────────────────────────────────────── */}
            <div className="p-4 border-t border-stone-800 bg-stone-950/80 mt-auto">
              <div className="tac-label mb-3 text-stone-500">INFRASTRUCTURE LEGEND</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                {[
                  { color: "#a3e635", label: "SUPPLIER" },
                  { color: "#4ade80", label: "WAREHOUSE" },
                  { color: "#34d399", label: "DIST CENTER" },
                  { color: "#86efac", label: "PORT" },
                ].map((l) => (
                  <div key={l.label} className="flex items-center gap-2.5">
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0 shadow-sm"
                      style={{ background: l.color }}
                    />
                    <span className="font-mono text-[10px] tracking-wide text-stone-300">{l.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === "THREATS" && (
          <div className="flex flex-col h-full overflow-hidden">
            <SectionHeader
              label="GLOBAL THREAT RADAR"
              count={state?.active_threats.length}
            />

            <div className="flex-1 overflow-y-auto">
              {state?.active_threats.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-stone-500 p-8 space-y-3">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="font-mono text-[10px] text-center uppercase tracking-widest">
                    ALL SECTORS SECURE<br/>NO ACTIVE EVENTS DETECTED
                  </span>
                </div>
              )}

              <div className="pb-4">
                {state?.active_threats.map((t) => (
                  <button
                    key={t.threat_id}
                    onClick={() => handleThreatClick(t)}
                    className="w-full text-left border-b border-stone-800 last:border-b-0 hover:bg-stone-800 transition-colors duration-150"
                    style={{
                      background:
                        selectedThreat?.threat_id === t.threat_id
                          ? "#292524" // stone-800 darker
                          : "transparent",
                      borderLeft: `3px solid ${SEV_COLOR[t.severity] ?? SEV_COLOR.unknown}`,
                    }}
                  >
                    <div className="px-4 py-3.5">
                      <div className="flex items-start justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[12px] font-bold text-stone-200 tracking-tight">
                            {EVENT_CODE[t.event_type] ?? "UNK"}
                          </span>
                          <span
                            className="font-mono text-[9px] uppercase px-1.5 py-0.5 rounded-sm shadow-sm font-semibold tracking-wider"
                            style={{
                              background: SEV_COLOR[t.severity] ?? SEV_COLOR.unknown,
                              color: "#0c0a09",
                            }}
                          >
                            {t.severity || "unknown"}
                          </span>
                        </div>
                        <span className="font-mono text-[9px] text-stone-500 tabular-nums" suppressHydrationWarning>
                          {new Date(t.ingested_at).toLocaleTimeString([], {
                            hour12: false,
                            hour: "2-digit",
                            minute: "2-digit",
                            timeZone: "UTC",
                          })}
                        </span>
                      </div>
                      
                      <div className="font-sans text-[12.5px] text-stone-300 leading-snug mb-3 pr-2">
                        {t.headline || t.description?.slice(0, 100) || "No description provided by source authority."}
                      </div>
                      
                      <div className="flex items-center justify-between border-t border-stone-800/80 pt-2.5">
                        <span className="font-mono text-[9px] text-stone-400 bg-stone-800 px-1.5 py-0.5 rounded font-medium tracking-widest">
                          {t.source.toUpperCase()}
                        </span>
                        <span className="font-mono text-[9px] text-stone-600 truncate max-w-[140px] tabular-nums">
                          ID: {t.threat_id.split('-').pop()}
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === "APPROVALS" && (
          <div className="flex flex-col h-full overflow-hidden">
            <SectionHeader
              label="HUMAN REVIEW REQUIRED"
              count={state?.pending_proposals.length}
              accent="text-amber-500"
            />
            
            <div className="flex-1 overflow-y-auto">
              {!state?.pending_proposals?.length ? (
                <div className="flex flex-col items-center justify-center h-full text-stone-500 p-8 space-y-3">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 019 9v.375M10.125 2.25A3.375 3.375 0 0113.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 013.375 3.375M9 15l2.25 2.25L15 12" />
                  </svg>
                  <span className="font-mono text-[10px] text-center uppercase tracking-widest leading-relaxed">
                    PIPELINE IDLE<br/>NO PENDING HITL APPROVALS
                  </span>
                </div>
              ) : (
                <div className="p-2 space-y-2 pb-6">
                  {state.pending_proposals.map((p) => (
                    <button
                      key={p.proposal_id}
                      onClick={() => {
                        setSelectedRoute(p);
                        setSelectedThreat(null);
                      }}
                      className="w-full text-left p-3.5 border border-stone-800 rounded shadow-sm hover:bg-stone-800 hover:border-stone-700 transition-all duration-150"
                      style={{
                        borderLeft: "3px solid #f59e0b",
                        background:
                          selectedRoute?.proposal_id === p.proposal_id
                            ? "#292524"
                            : "#1c1917",
                      }}
                    >
                      <div className="flex items-center justify-between mb-2 pb-2 border-b border-stone-800/60">
                        <span className="font-mono text-[10px] font-bold bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded shadow-sm tracking-wider">
                          HITL REVIEW
                        </span>
                        <span className="font-mono text-[10px] text-stone-400 tabular-nums">
                          SCORE: <span className="text-stone-300 font-bold">{p.attention_score.toFixed(3)}</span>
                        </span>
                      </div>
                      
                      <div className="font-mono text-[12px] text-stone-200 mb-3 truncate font-medium">
                        <span className="text-stone-500 mr-2 uppercase text-[10px]">TO</span> 
                        {p.proposed_supplier_name}
                      </div>
                      
                      <div className="grid grid-cols-2 gap-2 bg-stone-950/60 p-2.5 rounded border border-stone-800/80">
                        <MetaPair
                          label="EST. COST OFFSET"
                          value={`$${p.reroute_cost_usd.toLocaleString()}`}
                        />
                        <MetaPair
                          label="EST. DRIVE TIME"
                          value={`${Math.round(p.mapbox_drive_time_minutes / 60)} HRS`}
                        />
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
