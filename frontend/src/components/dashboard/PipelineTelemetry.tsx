"use client";

import { useEffect, useState } from "react";
import { subscribePipelineProgress, type PipelineProgressEvent } from "@/lib/api";

type AgentState = "idle" | "running" | "complete";

interface TelemetryMetrics {
  threats: number;
  var_usd: number;
  proposals: number;
  approved: number;
  hitl: number;
}

export default function PipelineTelemetry() {
  const [watcherState, setWatcherState] = useState<AgentState>("idle");
  const [procurementState, setProcurementState] = useState<AgentState>("idle");
  const [auditorState, setAuditorState] = useState<AgentState>("idle");
  const [isVisible, setIsVisible] = useState(false);
  const [metrics, setMetrics] = useState<TelemetryMetrics>({
    threats: 0,
    var_usd: 0,
    proposals: 0,
    approved: 0,
    hitl: 0,
  });

  useEffect(() => {
    const closeWS = subscribePipelineProgress((ev: PipelineProgressEvent) => {
      // Show HUD when pipeline starts
      if (ev.agent === "pipeline" && ev.status === "running") {
        setIsVisible(true);
        setWatcherState("idle");
        setProcurementState("idle");
        setAuditorState("idle");
        setMetrics({ threats: 0, var_usd: 0, proposals: 0, approved: 0, hitl: 0 });
      }

      // Hide HUD shortly after pipeline completes
      if (ev.agent === "pipeline" && ev.status === "complete") {
        setTimeout(() => setIsVisible(false), 8000);
      }

      if (ev.agent === "watcher") {
        setWatcherState(ev.status as AgentState);
        if (ev.status === "complete") {
          setMetrics(m => ({
            ...m,
            threats: ev.threats ?? m.threats,
            var_usd: ev.var_usd ?? m.var_usd,
          }));
        }
      }
      
      if (ev.agent === "procurement") {
        setProcurementState(ev.status as AgentState);
        if (ev.status === "complete") {
          setMetrics(m => ({
            ...m,
            proposals: ev.proposals ?? m.proposals,
          }));
        }
      }
      
      if (ev.agent === "auditor") {
        setAuditorState(ev.status as AgentState);
        if (ev.status === "complete") {
          setMetrics(m => ({
            ...m,
            approved: ev.approved ?? m.approved,
            hitl: ev.hitl ?? m.hitl,
          }));
        }
      }
    });

    return () => closeWS();
  }, []);

  if (!isVisible) return null;

  const renderNode = (name: string, stat: string, state: AgentState) => {
    const isRunning = state === "running";
    const isComplete = state === "complete";
    
    let colorClass = "border-stone-700 text-stone-500 bg-stone-900"; // idle
    let pulseHtml = null;

    if (isRunning) {
      colorClass = "border-lime-500 text-lime-400 bg-lime-950/40 shadow-[0_0_15px_rgba(163,230,53,0.3)]";
      pulseHtml = (
        <span className="absolute -top-1 -right-1 flex h-3 w-3">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-lime-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-3 w-3 bg-lime-500"></span>
        </span>
      );
    } else if (isComplete) {
      colorClass = "border-stone-500 text-stone-300 bg-stone-800/80";
    }

    return (
      <div className={`relative px-4 py-2 border ${colorClass} transition-all duration-300 backdrop-blur-md rounded-sm flex flex-col items-center w-36`}>
        {pulseHtml}
        <span className="font-mono text-[10px] tracking-widest uppercase mb-1">{name}</span>
        <span className={`font-mono text-xs font-bold ${isRunning ? "animate-pulse" : ""}`}>
          {stat}
        </span>
      </div>
    );
  };

  const renderConnector = (state: AgentState) => {
    const isActive = state === "running" || state === "complete";
    return (
      <div className="flex-1 h-px bg-stone-800 relative overflow-hidden">
        {isActive && (
          <div className="absolute top-0 left-0 h-full w-1/3 bg-gradient-to-r from-transparent via-lime-500 to-transparent animate-[slide-right_1.5s_linear_infinite]" />
        )}
      </div>
    );
  };

  return (
    <div className="absolute top-6 left-1/2 -translate-x-1/2 z-50 animate-[slide-down_0.3s_ease-out]">
      <div className="flex flex-col items-center gap-2 p-3 bg-stone-950/80 border border-stone-800 backdrop-blur-md rounded-md shadow-2xl">
        <div className="text-[9px] font-mono tracking-widest text-stone-400 uppercase mb-1">
          Cognitive Pipeline Active
        </div>
        <div className="flex items-center gap-2 w-[500px]">
          {renderNode("Watcher", `${metrics.threats} Threats`, watcherState)}
          {renderConnector(watcherState)}
          {renderNode("Procurement", `${metrics.proposals} Proposals`, procurementState)}
          {renderConnector(procurementState)}
          {renderNode("Auditor", `${metrics.approved} Prev | ${metrics.hitl} HITL`, auditorState)}
        </div>
        
        {/* Value at Risk ticker */}
        {watcherState !== "idle" && (
          <div className="mt-2 text-[10px] font-mono text-orange-500 animate-pulse">
            EVALUATING ${(metrics.var_usd / 1_000_000).toFixed(2)}M VALUE AT RISK
          </div>
        )}
      </div>
    </div>
  );
}
