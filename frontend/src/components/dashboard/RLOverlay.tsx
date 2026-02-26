"use client";

import type { Proposal } from "@/lib/api";

interface RLOverlayProps {
  proposal: Proposal | null;
  onClose: () => void;
}

export default function RLOverlay({ proposal, onClose }: RLOverlayProps) {
  if (!proposal) return null;

  // Use real auditor confidence score from the backend (persisted by _persist_verdict)
  const confidence = proposal.confidence;
  const confidenceDisplay = confidence != null ? confidence.toFixed(4) : "N/A";
  const rlAdjustment = proposal.rl_adjustment ?? 0;
  
  return (
    <div className="absolute top-20 right-4 w-96 border border-stone-700 bg-stone-950/90 backdrop-blur-md shadow-2xl z-40 animate-[slide-left_0.3s_ease-out]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-stone-800 bg-stone-900/50">
        <div className="flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a3e635" strokeWidth="2">
            <path d="M12 2L2 22h20L12 2z" />
          </svg>
          <span className="font-mono text-[10px] uppercase tracking-widest text-lime-400 font-bold">
            Auditor Reflection Matrix
          </span>
        </div>
        <button onClick={onClose} className="text-stone-500 hover:text-stone-300 font-mono text-xs">✕</button>
      </div>

      <div className="p-4 flex flex-col gap-4">
        {/* Proposal Info */}
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[9px] text-stone-500 uppercase tracking-widest">Target Node</span>
          <span className="font-mono text-xs text-stone-200">{proposal.proposed_supplier_name}</span>
          <span className="font-mono text-[10px] text-stone-500">{proposal.proposed_supplier_id}</span>
        </div>

        {/* Weights & Math */}
        <div className="border border-stone-800 bg-stone-900 rounded-sm p-3">
          <span className="font-mono text-[9px] text-stone-500 uppercase tracking-widest mb-2 block">Decision Calculus</span>
          
          <div className="flex flex-col gap-2 font-mono text-[10px]">
            <div className="flex justify-between">
              <span className="text-stone-400">Attention Score (w=0.3)</span>
              <span className="text-lime-400">{proposal.attention_score.toFixed(4)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-stone-400">Reroute Cost (w=0.2)</span>
              <span className="text-lime-400">${proposal.reroute_cost_usd.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-stone-400">Drive Time Penalty (w=0.15)</span>
              <span className="text-amber-400">-{proposal.mapbox_drive_time_minutes.toFixed(0)}m</span>
            </div>
            {rlAdjustment !== 0 && (
              <div className="flex justify-between">
                <span className="text-stone-400">RL Adjustment</span>
                <span className={rlAdjustment < 0 ? "text-red-400" : "text-lime-400"}>
                  {rlAdjustment > 0 ? "+" : ""}{rlAdjustment.toFixed(4)}
                </span>
              </div>
            )}
            
            <div className="h-px bg-stone-800 my-1" />
            
            <div className="flex justify-between font-bold">
              <span className="text-stone-300">Composite Confidence</span>
              <span className="text-white">{confidenceDisplay}</span>
            </div>
          </div>
        </div>

        {/* RL Penalty Warning */}
        {proposal.hitl_status === "awaiting_approval" && (
          <div className="border border-red-900/50 bg-red-950/20 rounded-sm p-3 flex flex-col gap-1 animate-pulse">
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="font-mono text-[10px] text-red-400 uppercase tracking-wider font-bold">
                RL Penalty Applied
              </span>
            </div>
            <p className="font-mono text-[9px] text-red-300/80 leading-relaxed">
              {proposal.audit_explanation || "Vendor reliability index penalized due to historical SLA failures. HITL approval required."}
            </p>
          </div>
        )}
        
        {proposal.hitl_status === "auto_approved" && (
          <div className="border border-lime-900/50 bg-lime-950/20 rounded-sm p-3 flex flex-col gap-1">
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-lime-500" />
              <span className="font-mono text-[10px] text-lime-400 uppercase tracking-wider font-bold">
                Auto-Execution Approved
              </span>
            </div>
            <p className="font-mono text-[9px] text-lime-300/80 leading-relaxed">
              {proposal.audit_explanation || "Confidence threshold met. No historical RL penalties detected for this vendor."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
