"use client";

import { useEffect, useRef, useState } from "react";

interface FinancialHUDProps {
  /** Total value at risk in USD from dashboard state */
  valueAtRisk: number;
  /** Number of active reroute proposals (approved + auto_approved) */
  reroutesActive: number;
  /** Number of active threats currently being monitored */
  activeThreats: number;
  /** Number of disruptions prevented (proposals count) */
  disruptionsPrevented: number;
}

// ── Animated counter hook ──────────────────────────────────────────────────

function useAnimatedCounter(target: number, duration = 1200): number {
  const [value, setValue] = useState(0);
  const prevRef = useRef(0);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    const start = prevRef.current;
    const diff = target - start;
    if (Math.abs(diff) < 0.01) {
      setValue(target);
      prevRef.current = target;
      return;
    }

    const startTime = performance.now();

    function tick(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + diff * eased;
      setValue(current);

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        prevRef.current = target;
      }
    }

    frameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, duration]);

  return value;
}

// ── Net savings estimation ─────────────────────────────────────────────────
// Simplified version of the simulate.py counterfactual model constants
const AVOIDANCE_EFFICIENCY = 0.73;
const REROUTE_OVERHEAD_RATE = 0.18;
const AVG_DETECTION_RATE = 0.76;

function estimateNetSavings(valueAtRisk: number, reroutesActive: number): number {
  if (valueAtRisk <= 0 || reroutesActive <= 0) return 0;
  const detected = valueAtRisk * AVG_DETECTION_RATE;
  const avoided = detected * AVOIDANCE_EFFICIENCY;
  const overhead = avoided * REROUTE_OVERHEAD_RATE;
  return avoided - overhead;
}

function estimateROI(netSavings: number, valueAtRisk: number): number {
  if (valueAtRisk <= 0) return 0;
  const overhead = valueAtRisk * AVG_DETECTION_RATE * AVOIDANCE_EFFICIENCY * REROUTE_OVERHEAD_RATE;
  return overhead > 0 ? netSavings / overhead : 0;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function FinancialHUD({
  valueAtRisk,
  reroutesActive,
  activeThreats,
  disruptionsPrevented,
}: FinancialHUDProps) {
  const netSavings = estimateNetSavings(valueAtRisk, reroutesActive);
  const roi = estimateROI(netSavings, valueAtRisk);

  const animSavings = useAnimatedCounter(netSavings / 1_000_000);
  const animROI = useAnimatedCounter(roi);
  const animDisruptions = useAnimatedCounter(disruptionsPrevented);
  const animThreats = useAnimatedCounter(activeThreats);

  // Don't render if no data
  if (activeThreats === 0 && valueAtRisk === 0) return null;

  return (
    <div
      className="absolute top-4 left-1/2 -translate-x-1/2 z-40 flex items-stretch gap-px"
      style={{
        borderRadius: "3px",
        overflow: "hidden",
      }}
    >
      {/* Saved */}
      <MetricCard
        label="NET SAVED"
        value={`$${animSavings.toFixed(2)}M`}
        color="#a3e635"
        glowColor="rgba(163, 230, 53, 0.15)"
        pulse
      />

      {/* ROI */}
      <MetricCard
        label="ROI"
        value={`${animROI.toFixed(1)}×`}
        color="#34d399"
        glowColor="rgba(52, 211, 153, 0.12)"
      />

      {/* Disruptions Prevented */}
      <MetricCard
        label="DISRUPTIONS BLOCKED"
        value={Math.round(animDisruptions).toString()}
        color="#fbbf24"
        glowColor="rgba(251, 191, 36, 0.10)"
      />

      {/* Active Threats */}
      <MetricCard
        label="ACTIVE THREATS"
        value={Math.round(animThreats).toString()}
        color={activeThreats > 5 ? "#ef4444" : "#f59e0b"}
        glowColor={activeThreats > 5 ? "rgba(239, 68, 68, 0.12)" : "rgba(245, 158, 11, 0.10)"}
      />
    </div>
  );
}

// ── Single metric card ─────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  color,
  glowColor,
  pulse = false,
}: {
  label: string;
  value: string;
  color: string;
  glowColor: string;
  pulse?: boolean;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center px-5 py-2.5 min-w-[120px]"
      style={{
        background: `linear-gradient(180deg, rgba(28,25,23,0.95) 0%, rgba(12,10,9,0.95) 100%)`,
        backdropFilter: "blur(12px)",
        borderBottom: `2px solid ${color}`,
        boxShadow: `inset 0 -8px 20px ${glowColor}`,
      }}
    >
      <span
        className="text-[8px] font-mono uppercase tracking-[0.2em] mb-1"
        style={{ color: "rgba(168,162,158,0.7)" }}
      >
        {label}
      </span>
      <span
        className="text-[18px] font-mono font-bold tabular-nums leading-none"
        style={{
          color,
          textShadow: `0 0 12px ${glowColor}`,
          animation: pulse ? "financial-pulse 2s ease-in-out infinite" : undefined,
        }}
      >
        {value}
      </span>
    </div>
  );
}
