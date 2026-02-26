import { Dispatch, SetStateAction } from "react";
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
        <span className={`font-mono text-[9px] font-bold ${accent}`}>
          {count}
        </span>
      )}
    </div>
  );
}

function MetaPair({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="tac-label">{label}</span>
      <span className="font-mono text-[9px] font-bold text-stone-200">
        {value}
      </span>
    </span>
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
  return (
    <aside className="flex flex-col w-[300px] shrink-0 bg-stone-900 border-r border-stone-800 overflow-hidden z-10">
      {/* ── Wordmark ─────────────────────────────────────── */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-stone-800">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
          <polygon
            points="10,2 18,7 18,13 10,18 2,13 2,7"
            stroke="#a3e635"
            strokeWidth="1.5"
            fill="none"
          />
          <circle cx="10" cy="10" r="2.5" fill="#a3e635" />
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
            style={{
              background: error ? "#dc2626" : "#a3e635",
              boxShadow: error ? "0 0 4px #dc2626" : "0 0 4px #a3e635",
            }}
          />
          <span className="font-mono text-[9px] uppercase tracking-widest text-stone-500">
            {error ? "OFFLINE" : "LIVE"}
          </span>
        </span>
        <span className="font-mono text-[9px] text-stone-600">
          {lastSync ? lastSync.toLocaleTimeString([], { hour12: false }) : "--:--:--"}
        </span>
        {error && (
          <span className="font-mono text-[9px] text-red-500 truncate">
            {error}
          </span>
        )}
      </div>

      {/* ── KPI row ───────────────────────────────────────── */}
      <div className="grid grid-cols-4 border-b border-stone-800">
        <Kpi
          label="THREATS"
          value={state?.active_threats.length ?? "—"}
          accent="text-red-500"
        />
        <Kpi
          label="NODES"
          value={state?.erp_locations.length ?? "—"}
          accent="text-lime-400"
        />
        <Kpi label="VAR $M" value={var_millions} accent="text-orange-500" />
        <Kpi
          label="ROUTES"
          value={state?.active_routes.length ?? "—"}
          accent="text-lime-400"
        />
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
      <SectionHeader
        label="ACTIVE THREAT EVENTS"
        count={state?.active_threats.length}
      />

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
              background:
                selectedThreat?.threat_id === t.threat_id
                  ? "#292524"
                  : "transparent",
              borderLeft: `2px solid ${SEV_COLOR[t.severity] ?? SEV_COLOR.unknown}`,
            }}
          >
            <div className="px-3 py-2">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="font-mono text-[10px] font-bold text-stone-300">
                  {EVENT_CODE[t.event_type] ?? "UNK"}
                </span>
                <span
                  className="font-mono text-[8px] uppercase px-1 py-px"
                  style={{
                    background: SEV_COLOR[t.severity] ?? SEV_COLOR.unknown,
                    color: "#0c0a09",
                    borderRadius: "1px",
                  }}
                >
                  {t.severity || "unknown"}
                </span>
                <span className="font-mono text-[9px] text-stone-600 ml-auto">
                  {new Date(t.ingested_at).toLocaleTimeString([], {
                    hour12: false,
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
              <div className="font-mono text-[10px] text-stone-400 truncate leading-tight">
                {t.headline || t.description?.slice(0, 72) || "No description"}
              </div>
              <div className="flex gap-2 mt-0.5">
                <span className="tac-label">{t.source.toUpperCase()}</span>
                <span className="tac-label truncate">
                  {t.threat_id.slice(0, 24)}
                </span>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* ── HITL pending proposals ────────────────────────── */}
      {state?.pending_proposals && state.pending_proposals.length > 0 && (
        <>
          <SectionHeader
            label="AWAITING APPROVAL"
            count={state.pending_proposals.length}
            accent="text-amber-500"
          />
          <div className="overflow-y-auto max-h-[30vh]">
            {state.pending_proposals.map((p) => (
              <button
                key={p.proposal_id}
                onClick={() => {
                  setSelectedRoute(p);
                  setSelectedThreat(null);
                }}
                className="w-full text-left px-3 py-2 border-b border-stone-800 hover:bg-stone-800 transition-colors"
                style={{
                  borderLeft: "2px solid #f59e0b",
                  background:
                    selectedRoute?.proposal_id === p.proposal_id
                      ? "#292524"
                      : "transparent",
                }}
              >
                <div className="flex items-baseline gap-1.5 mb-0.5">
                  <span className="font-mono text-[10px] font-bold text-amber-400">
                    HITL
                  </span>
                  <span className="font-mono text-[9px] text-stone-400 truncate">
                    {p.proposed_supplier_name}
                  </span>
                </div>
                <div className="flex gap-3">
                  <MetaPair
                    label="COST"
                    value={`$${p.reroute_cost_usd.toLocaleString()}`}
                  />
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
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: l.color }}
              />
              <span className="tac-label">{l.label}</span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
