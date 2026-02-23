"use client";

import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import ChatToMap from "@/components/chat/ChatToMap";
import {
  fetchDashboardState,
  triggerPipeline,
  triggerIngest,
  type DashboardState,
  type WeatherThreat,
  type ERPLocation,
} from "@/lib/api";

// Dynamic import for Mapbox (no SSR — requires window/DOM)
const AegisGlobe = dynamic(() => import("@/components/map/AegisGlobe"), {
  ssr: false,
  loading: () => (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "#0a0e17", color: "#64748b" }}>
      Initializing globe...
    </div>
  ),
});

const POLL_MS = 30_000;

export default function DashboardPage() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [highlighted, setHighlighted] = useState<string[]>([]);
  const [selectedThreat, setSelectedThreat] = useState<WeatherThreat | null>(null);
  const [running, setRunning] = useState<"idle" | "ingest" | "pipeline">("idle");
  const [error, setError] = useState<string | null>(null);

  // ── Fetch dashboard state ─────────────────────────────────────
  const loadState = useCallback(async () => {
    try {
      const data = await fetchDashboardState();
      setState(data);
      setError(null);
    } catch {
      setError("Backend offline. Start the FastAPI server on :8000.");
    }
  }, []);

  useEffect(() => {
    loadState();
    const interval = setInterval(loadState, POLL_MS);
    return () => clearInterval(interval);
  }, [loadState]);

  // ── Action handlers ───────────────────────────────────────────
  const handleIngest = async () => {
    setRunning("ingest");
    try {
      await triggerIngest();
      await loadState();
    } catch {
      setError("Ingest failed.");
    }
    setRunning("idle");
  };

  const handlePipeline = async () => {
    setRunning("pipeline");
    try {
      await triggerPipeline();
      await loadState();
    } catch {
      setError("Pipeline failed.");
    }
    setRunning("idle");
  };

  const handleLocationClick = (loc: ERPLocation) => {
    setHighlighted([loc.location_id]);
  };

  const handleThreatClick = (threat: WeatherThreat) => {
    setSelectedThreat(threat);
  };

  return (
    <div style={styles.layout}>
      {/* ── Left: Status Panel ─────────────────────────────────── */}
      <aside style={styles.sidebar}>
        <div style={styles.logo}>
          <span style={styles.logoIcon}>&#9741;</span>
          <div>
            <div style={styles.logoTitle}>AegisChain</div>
            <div style={styles.logoSub}>Cognitive Supply Chain Immune System</div>
          </div>
        </div>

        {/* KPIs */}
        <div style={styles.kpiGrid}>
          <KpiCard
            label="Active Threats"
            value={state?.active_threats.length ?? "-"}
            color="#ef4444"
          />
          <KpiCard
            label="ERP Locations"
            value={state?.erp_locations.length ?? "-"}
            color="#3b82f6"
          />
          <KpiCard
            label="Value at Risk"
            value={state ? `$${(state.total_value_at_risk / 1_000_000).toFixed(1)}M` : "-"}
            color="#f59e0b"
          />
          <KpiCard
            label="Active Routes"
            value={state?.active_routes.length ?? "-"}
            color="#22c55e"
          />
        </div>

        {/* Actions */}
        <div style={styles.actions}>
          <button onClick={handleIngest} disabled={running !== "idle"} style={styles.actionBtn}>
            {running === "ingest" ? "Polling..." : "Poll NOAA / FIRMS"}
          </button>
          <button onClick={handlePipeline} disabled={running !== "idle"} style={{ ...styles.actionBtn, background: "#1e3a5f", borderColor: "#3b82f6" }}>
            {running === "pipeline" ? "Running..." : "Run Agent Pipeline"}
          </button>
        </div>

        {/* Threat list */}
        <div style={styles.sectionTitle}>Active Threats</div>
        <div style={styles.threatList}>
          {state?.active_threats.slice(0, 15).map((t) => (
            <div
              key={t.threat_id}
              onClick={() => handleThreatClick(t)}
              style={{
                ...styles.threatItem,
                borderLeftColor: SEVERITY_COLORS[t.severity] || "#8b5cf6",
                background: selectedThreat?.threat_id === t.threat_id ? "#1e293b" : "transparent",
              }}
            >
              <div style={styles.threatType}>
                {t.event_type.replace("_", " ")}
                <span style={{ ...styles.severityBadge, background: SEVERITY_COLORS[t.severity] }}>
                  {t.severity}
                </span>
              </div>
              <div style={styles.threatHeadline}>{t.headline || t.description?.slice(0, 80)}</div>
              <div style={styles.threatMeta}>
                {t.source.toUpperCase()} &middot; {new Date(t.ingested_at).toLocaleTimeString()}
              </div>
            </div>
          )) ?? (
            <div style={{ color: "#64748b", fontSize: 13, padding: "8px 0" }}>
              {error || "No active threats"}
            </div>
          )}
        </div>

        {/* Pending proposals */}
        {state?.pending_proposals && state.pending_proposals.length > 0 && (
          <>
            <div style={styles.sectionTitle}>Pending Approvals</div>
            <div style={styles.threatList}>
              {state.pending_proposals.map((p) => (
                <div key={p.proposal_id} style={{ ...styles.threatItem, borderLeftColor: "#f59e0b" }}>
                  <div style={styles.threatType}>
                    {p.proposed_supplier_name}
                    <span style={{ ...styles.severityBadge, background: "#92400e" }}>HITL</span>
                  </div>
                  <div style={styles.threatHeadline}>
                    ${p.reroute_cost_usd.toLocaleString()} &middot; Score: {p.attention_score.toFixed(4)}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </aside>

      {/* ── Center: Map ────────────────────────────────────────── */}
      <main style={styles.mapArea}>
        <AegisGlobe
          threats={state?.active_threats ?? []}
          locations={state?.erp_locations ?? []}
          routes={state?.active_routes ?? []}
          highlightedEntities={highlighted}
          onLocationClick={handleLocationClick}
          onThreatClick={handleThreatClick}
        />

        {/* Map overlay: status bar */}
        <div style={styles.mapOverlay}>
          <span style={styles.overlayDot(error ? "#ef4444" : "#22c55e")} />
          <span style={{ fontSize: 12, color: "#94a3b8" }}>
            {error ? "Disconnected" : "Live"} &middot; {state?.active_threats.length ?? 0} threats &middot; ${((state?.total_value_at_risk ?? 0) / 1_000_000).toFixed(1)}M at risk
          </span>
        </div>
      </main>

      {/* ── Right: Chat Panel ──────────────────────────────────── */}
      <aside style={styles.chatPanel}>
        <ChatToMap
          contextThreatId={selectedThreat?.threat_id}
          onHighlight={setHighlighted}
        />
      </aside>
    </div>
  );
}

// ── KPI Card component ──────────────────────────────────────────
function KpiCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div style={styles.kpiCard}>
      <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

// ── Colors ──────────────────────────────────────────────────────
const SEVERITY_COLORS: Record<string, string> = {
  extreme: "#ef4444",
  severe: "#f97316",
  moderate: "#f59e0b",
  minor: "#3b82f6",
  unknown: "#8b5cf6",
};

// ── Styles ──────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties | ((...args: any[]) => React.CSSProperties)> = {
  layout: {
    display: "flex",
    height: "100vh",
    width: "100vw",
    overflow: "hidden",
    background: "#0a0e17",
  },
  sidebar: {
    width: 320,
    flexShrink: 0,
    background: "#111827",
    borderRight: "1px solid #2a3040",
    display: "flex",
    flexDirection: "column",
    overflowY: "auto",
    padding: 16,
    gap: 12,
  },
  logo: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    paddingBottom: 12,
    borderBottom: "1px solid #2a3040",
  },
  logoIcon: {
    fontSize: 28,
    color: "#3b82f6",
  },
  logoTitle: {
    fontSize: 16,
    fontWeight: 700,
    color: "#e2e8f0",
    letterSpacing: "-0.02em",
  },
  logoSub: {
    fontSize: 10,
    color: "#64748b",
    letterSpacing: "0.05em",
    textTransform: "uppercase" as const,
  },
  kpiGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 8,
  },
  kpiCard: {
    background: "#0f1420",
    border: "1px solid #2a3040",
    borderRadius: 8,
    padding: "10px 12px",
  },
  actions: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
  },
  actionBtn: {
    width: "100%",
    padding: "8px 12px",
    fontSize: 12,
    fontWeight: 600,
    background: "#1a2332",
    color: "#e2e8f0",
    border: "1px solid #2a3040",
    borderRadius: 6,
    cursor: "pointer",
    transition: "background 0.15s",
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: 600,
    color: "#64748b",
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    marginTop: 4,
  },
  threatList: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 4,
    flex: 1,
    overflowY: "auto" as const,
  },
  threatItem: {
    padding: "8px 10px",
    borderRadius: 6,
    borderLeft: "3px solid",
    cursor: "pointer",
    transition: "background 0.15s",
  },
  threatType: {
    fontSize: 12,
    fontWeight: 600,
    color: "#e2e8f0",
    display: "flex",
    alignItems: "center",
    gap: 6,
    textTransform: "capitalize" as const,
  },
  severityBadge: {
    fontSize: 9,
    fontWeight: 600,
    padding: "1px 5px",
    borderRadius: 3,
    color: "#fff",
    textTransform: "uppercase" as const,
  },
  threatHeadline: {
    fontSize: 11,
    color: "#94a3b8",
    marginTop: 2,
    lineHeight: "1.3",
    overflow: "hidden" as const,
    textOverflow: "ellipsis" as const,
    whiteSpace: "nowrap" as const,
  },
  threatMeta: {
    fontSize: 10,
    color: "#64748b",
    marginTop: 2,
  },
  mapArea: {
    flex: 1,
    position: "relative" as const,
  },
  mapOverlay: {
    position: "absolute" as const,
    bottom: 16,
    left: 16,
    display: "flex",
    alignItems: "center",
    gap: 6,
    background: "rgba(17, 24, 39, 0.85)",
    backdropFilter: "blur(8px)",
    border: "1px solid #2a3040",
    borderRadius: 8,
    padding: "6px 12px",
  },
  overlayDot: (color: string): React.CSSProperties => ({
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: color,
    boxShadow: `0 0 6px ${color}`,
  }),
  chatPanel: {
    width: 380,
    flexShrink: 0,
  },
};
