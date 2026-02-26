"use client";

import {
  useEffect,
  useState,
  useCallback,
  useRef,
  type FormEvent,
} from "react";
import dynamic from "next/dynamic";
import ChatToMap from "@/components/chat/ChatToMap";
import GlobeErrorBoundary from "@/components/map/GlobeErrorBoundary";
import PipelineTelemetry from "@/components/dashboard/PipelineTelemetry";
import ThreatPanel from "@/components/dashboard/ThreatPanel";
import RLOverlay from "@/components/dashboard/RLOverlay";
import FinancialHUD from "@/components/dashboard/FinancialHUD";
import TimeSlider from "@/components/map/TimeSlider";
import {
  PipelineProgressProvider,
  usePipelineProgress,
} from "@/components/providers/PipelineProgressProvider";
import {
  fetchDashboardState,
  triggerPipeline,
  triggerIngest,
  subscribeToEvents,
  createERPLocation,
  type DashboardState,
  type WeatherThreat,
  type ERPLocation,
  type ERPLocationUpsert,
  type PipelineProgressEvent,
  type Proposal,
  type XRayTarget,
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
  severe: "#ea580c",
  moderate: "#d97706",
  minor: "#ca8a04",
  unknown: "#78716c",
};

// Event type → short code for dense display
const EVENT_CODE: Record<string, string> = {
  hurricane: "HUR",
  tornado: "TOR",
  flood: "FLD",
  winter_storm: "WNT",
  severe_thunderstorm: "TST",
  heat_wave: "HEW",
  wildfire: "WFR",
  earthquake: "EQK",
  tsunami: "TSU",
  unknown: "UNK",
};

import useSWR from "swr";
const fetcher = (url: string) =>
  fetch(url).then((res) => {
    if (!res.ok) throw new Error("Backend offline");
    return res.json();
  });

export default function DashboardPage() {
  return (
    <PipelineProgressProvider>
      <DashboardInner />
    </PipelineProgressProvider>
  );
}

function DashboardInner() {
  const {
    data: state,
    error: swrError,
    mutate,
  } = useSWR<DashboardState>(
    `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/dashboard/state`,
    fetcher,
    {
      refreshInterval: POLL_MS,
      keepPreviousData: true,
      errorRetryCount: 3,
      errorRetryInterval: 5000,
    },
  );

  const [highlighted, setHighlighted] = useState<string[]>([]);
  const [xrayTargets, setXrayTargets] = useState<XRayTarget[]>([]);
  const [selectedThreat, setSelectedThreat] = useState<WeatherThreat | null>(
    null,
  );
  const [selectedRoute, setSelectedRoute] = useState<Proposal | null>(null);
  const [running, setRunning] = useState<"idle" | "ingest" | "pipeline">(
    "idle",
  );
  const [manualError, setManualError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [pipelineMetrics, setPipelineMetrics] = useState({
    approved: 0,
    hitl: 0,
  });
  const [simulatedOffsetHours, setSimulatedOffsetHours] = useState(0);

  const error =
    manualError || (swrError ? "SYS:DISCONNECTED — backend offline" : null);

  const loadState = useCallback(async () => {
    try {
      await mutate();
      setLastSync(new Date());
      setManualError(null);
    } catch {
      setManualError("SYS:DISCONNECTED — backend offline");
    }
  }, [mutate]);

  // Track whether initial sync timestamp has been set
  const lastSyncSetRef = useRef(false);

  useEffect(() => {
    // Initial sync time record
    if (state && !lastSyncSetRef.current) {
      lastSyncSetRef.current = true;
      setLastSync(new Date());
    }
  }, [state]);

  useEffect(() => {
    // SSE real-time push — reload dashboard on any backend event
    const closeSSE = subscribeToEvents(
      () => loadState(),
      () => {
        /* connection errors are normal during backend restart — ignore */
      },
    );

    return () => {
      closeSSE();
    };
  }, [loadState]);

  // Pipeline progress from shared WebSocket context (BUG-008 fix)
  const { lastEvent: pipelineEvent } = usePipelineProgress();
  useEffect(() => {
    if (!pipelineEvent) return;
    if (pipelineEvent.agent === "auditor" && pipelineEvent.status === "complete") {
      setPipelineMetrics({
        approved: pipelineEvent.approved ?? 0,
        hitl: pipelineEvent.hitl ?? 0,
      });
      loadState();
    }
  }, [pipelineEvent, loadState]);

  const handleIngest = async () => {
    setRunning("ingest");
    try {
      await triggerIngest();
      await loadState();
    } catch {
      setManualError("INGEST:FAILED");
    }
    setRunning("idle");
  };

  const handlePipeline = async () => {
    setRunning("pipeline");
    try {
      await triggerPipeline();
      await loadState();
    } catch {
      setManualError("PIPELINE:FAILED");
    }
    setRunning("idle");
  };

  const handleLocationClick = useCallback(
    (loc: ERPLocation) => setHighlighted([loc.location_id]),
    [],
  );
  const handleThreatClick = useCallback((threat: WeatherThreat) => {
    setSelectedThreat(threat);
    setSelectedRoute(null);
  }, []);

  const var_millions = ((state?.total_value_at_risk ?? 0) / 1_000_000).toFixed(
    2,
  );
  const reroutes_count =
    (state?.active_routes.length ?? 0) + pipelineMetrics.approved;
  const has_pending =
    (state?.pending_proposals.length ?? 0) > 0 || pipelineMetrics.hitl > 0;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-stone-950 text-stone-200">
      <ThreatPanel
        state={state}
        error={error}
        lastSync={lastSync}
        running={running}
        pipelineMetrics={pipelineMetrics}
        selectedThreat={selectedThreat}
        selectedRoute={selectedRoute}
        handleIngest={handleIngest}
        handlePipeline={handlePipeline}
        handleThreatClick={handleThreatClick}
        setSelectedRoute={setSelectedRoute}
        setSelectedThreat={setSelectedThreat}
        loadState={loadState}
        var_millions={var_millions}
      />

      {/* ══════════════════════════════════════════════════════
          CENTER — Satellite Map
      ══════════════════════════════════════════════════════ */}
      <main className="relative flex-1 bg-stone-950">
        {/* ── Financial Impact HUD ─────────────────────────── */}
        <FinancialHUD
          valueAtRisk={state?.total_value_at_risk ?? 0}
          reroutesActive={state?.active_routes.length ?? 0}
          activeThreats={state?.active_threats.length ?? 0}
          disruptionsPrevented={reroutes_count}
        />

        <GlobeErrorBoundary>
          <AegisGlobe
            threats={state?.active_threats ?? []}
            locations={state?.erp_locations ?? []}
            routes={state?.active_routes ?? []}
            highlightedEntities={highlighted}
            xrayTargets={xrayTargets}
            selectedThreatId={selectedThreat?.threat_id}
            simulatedOffsetHours={simulatedOffsetHours}
            onLocationClick={handleLocationClick}
            onThreatClick={handleThreatClick}
          />

          {/* Time Machine Slider */}
          <TimeSlider onTimeChange={setSimulatedOffsetHours} maxHours={72} />

          {/* Overlays */}
          <PipelineTelemetry />
          <RLOverlay
            proposal={selectedRoute}
            onClose={() => setSelectedRoute(null)}
          />
        </GlobeErrorBoundary>

        {/* ── Bottom-left HUD strip ─────────────────────────── */}
        <div
          className="absolute bottom-5 left-4 flex items-center gap-3 px-3 py-1.5 border border-stone-700"
          style={{
            background: "rgba(28,25,23,0.88)",
            backdropFilter: "blur(6px)",
            borderRadius: "2px",
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: error
                ? "#dc2626"
                : has_pending
                  ? "#f59e0b"
                  : "#a3e635",
              boxShadow: error
                ? "0 0 5px #dc2626"
                : has_pending
                  ? "0 0 5px #f59e0b"
                  : "0 0 5px #a3e635",
            }}
          />
          <span className="font-mono text-[10px] text-stone-400 uppercase tracking-wider">
            {error
              ? "DISCONNECTED"
              : has_pending
                ? "AWAITING APPROVAL"
                : "SATELLITE FEED LIVE"}
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
            className="absolute top-4 left-1/2 -translate-x-1/2 px-4 py-2 border border-stone-700 flex items-center gap-4 z-50"
            style={{
              background: "rgba(28,25,23,0.92)",
              backdropFilter: "blur(6px)",
              borderRadius: "2px",
            }}
          >
            <span
              className="font-mono text-[10px] font-bold uppercase"
              style={{ color: SEV_COLOR[selectedThreat.severity] }}
            >
              {EVENT_CODE[selectedThreat.event_type]} /{" "}
              {selectedThreat.severity.toUpperCase()}
            </span>
            <span className="w-px h-3 bg-stone-700" />
            <span className="font-mono text-[10px] text-stone-300 max-w-xs truncate">
              {selectedThreat.headline ||
                selectedThreat.description?.slice(0, 80)}
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
          onXray={setXrayTargets}
        />
      </aside>
    </div>
  );
}
