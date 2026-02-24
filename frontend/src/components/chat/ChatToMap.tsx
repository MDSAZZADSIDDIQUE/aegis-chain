"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  sendChatMessage,
  subscribePipelineProgress,
  type ChatResponse,
  type PipelineProgressEvent,
} from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

type Role = "operator" | "auditor" | "system" | "error";

interface LogEntry {
  id: string;
  role: Role;
  text: string;
  esql?: string | null;
  kvPairs?: Record<string, string>;
  highlightedEntities?: string[];
  ts: Date;
}

interface ChatToMapProps {
  contextThreatId?: string;
  onHighlight: (entities: string[]) => void;
}

// ── Role display metadata ──────────────────────────────────────────────────

const ROLE_META: Record<Role, { id: string; color: string; prefix: string }> = {
  operator: { id: "OPERATOR",  color: "#a8a29e", prefix: ">" },
  auditor:  { id: "AUDITOR-3", color: "#a3e635", prefix: "»" },
  system:   { id: "SYS",       color: "#78716c", prefix: "#" },
  error:    { id: "ERR",       color: "#dc2626", prefix: "!" },
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTime(d: Date) {
  return d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Try to extract key-value pairs from agent response text for structured display. */
function extractKVPairs(text: string): Record<string, string> | undefined {
  const result: Record<string, string> = {};
  const patterns: [RegExp, string][] = [
    [/attention[_\s]score[:\s]+([0-9.]+)/i,    "attention_score"],
    [/reliability[_\s]index[:\s]+([0-9.]+)/i,  "reliability_idx"],
    [/drive[_\s]time[:\s]+([\d.]+)\s*min/i,    "drive_time_min"],
    [/cost[:\s]+\$?([\d,]+(?:\.\d{2})?)/i,     "reroute_cost"],
    [/sla[_\s]match[:\s]+([0-9.]+)/i,          "sla_match"],
    [/confidence[:\s]+([0-9.]+)/i,              "confidence"],
    [/\$([0-9,.]+)M?\s+(?:at risk|VAR)/i,      "value_at_risk"],
    [/(\d+)\s+active\s+threats?/i,              "active_threats"],
  ];
  for (const [rx, key] of patterns) {
    const m = text.match(rx);
    if (m) result[key] = m[1].replace(/,/g, "");
  }
  return Object.keys(result).length > 0 ? result : undefined;
}

// ── Pipeline progress formatter ────────────────────────────────────────────

const AGENT_LABEL: Record<string, string> = {
  watcher:     "Agent 1 · Watcher",
  procurement: "Agent 2 · Procurement",
  auditor:     "Agent 3 · Auditor",
  pipeline:    "Pipeline",
};

function formatProgressEvent(ev: PipelineProgressEvent): string {
  const label = AGENT_LABEL[ev.agent] ?? ev.agent.toUpperCase();

  if (ev.status === "running") {
    const extra =
      ev.correlations !== undefined ? ` — processing ${ev.correlations} correlations` :
      ev.proposals    !== undefined ? ` — evaluating ${ev.proposals} proposals`        : "";
    return `[${label}] running${extra}…`;
  }

  if (ev.status === "complete") {
    const parts: string[] = [];
    if (ev.threats     !== undefined) parts.push(`${ev.threats} threats`);
    if (ev.at_risk     !== undefined) parts.push(`${ev.at_risk} at-risk nodes`);
    if (ev.bottlenecks !== undefined && ev.bottlenecks > 0)
                                      parts.push(`${ev.bottlenecks} bottlenecks`);
    if (ev.var_usd     !== undefined && ev.var_usd > 0)
                                      parts.push(`$${(ev.var_usd / 1e6).toFixed(2)}M VAR`);
    if (ev.proposals   !== undefined) parts.push(`${ev.proposals} proposals`);
    if (ev.approved    !== undefined) parts.push(`${ev.approved} approved`);
    if (ev.hitl        !== undefined) parts.push(`${ev.hitl} HITL`);
    if (ev.rejected    !== undefined) parts.push(`${ev.rejected} rejected`);
    if (ev.actions     !== undefined) parts.push(`${ev.actions} actions taken`);
    if (ev.reason      === "no_correlations") parts.push("no threats active");
    if (ev.reason      === "no_proposals")    parts.push("no proposals generated");
    const detail = parts.length > 0 ? `: ${parts.join(" · ")}` : "";
    return `[${label}] complete${detail}`;
  }

  return `[${label}] ${ev.status}`;
}

// ── Component ─────────────────────────────────────────────────────────────

export default function ChatToMap({ contextThreatId, onHighlight }: ChatToMapProps) {
  const [log, setLog] = useState<LogEntry[]>([
    {
      id: "boot",
      role: "system",
      text: "AegisChain v1.0.0 — Cognitive Supply Chain Immune System\nAuditor Agent online. ES|QL engine connected.\nType a query or press ENTER to confirm.",
      ts: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [expandedEsql, setExpandedEsql] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [log]);

  const pushEntry = useCallback(
    (entry: LogEntry) => setLog((prev) => [...prev, entry]),
    [],
  );

  // ── Pipeline progress WebSocket ─────────────────────────────────────────
  useEffect(() => {
    const close = subscribePipelineProgress((ev) => {
      pushEntry({
        id:   `ws-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        role: "system",
        text: formatProgressEvent(ev),
        ts:   new Date(),
      });
    });
    return close;
  }, [pushEntry]);

  const handleSend = async () => {
    const question = input.trim();
    if (!question || loading) return;

    const userEntry: LogEntry = {
      id: `u-${Date.now()}`,
      role: "operator",
      text: question,
      ts: new Date(),
    };
    pushEntry(userEntry);
    setInput("");
    setLoading(true);

    try {
      const res: ChatResponse = await sendChatMessage(question, contextThreatId);

      const agentEntry: LogEntry = {
        id: `a-${Date.now()}`,
        role: "auditor",
        text: res.answer,
        esql: res.esql_query,
        kvPairs: extractKVPairs(res.answer),
        highlightedEntities: res.highlighted_entities,
        ts: new Date(),
      };
      pushEntry(agentEntry);

      if (res.highlighted_entities?.length) {
        onHighlight(res.highlighted_entities);
      }
    } catch {
      pushEntry({
        id: `e-${Date.now()}`,
        role: "error",
        text: "CONNECTION_REFUSED — backend unreachable on :8000",
        ts: new Date(),
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full bg-stone-950 font-mono">

      {/* ── Panel header ─────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 bg-stone-900 border-b border-stone-800 shrink-0">
        {/* canopy accent bar */}
        <div className="w-0.5 h-4 bg-lime-500" />
        <div className="flex-1">
          <div className="text-[10px] font-semibold tracking-widest uppercase text-stone-300">
            AUDITOR COMMAND LOG
          </div>
          <div className="text-[8px] tracking-wider uppercase text-stone-600">
            ES|QL · REFLECTION PATTERN · HITL ENABLED
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: loading ? "#f59e0b" : "#a3e635",
                     boxShadow: loading ? "0 0 4px #f59e0b" : "0 0 4px #a3e635" }}
          />
          <span className="text-[8px] uppercase tracking-wider text-stone-600">
            {loading ? "QUERYING" : "READY"}
          </span>
        </div>
      </div>

      {/* ── Context thread tag ───────────────────────────────── */}
      {contextThreatId && (
        <div className="flex items-center gap-2 px-3 py-1 bg-lime-950 border-b border-lime-900 shrink-0">
          <span className="text-[8px] uppercase tracking-widest text-lime-700">THREAT CTX</span>
          <span className="text-[9px] text-lime-400 truncate">{contextThreatId}</span>
        </div>
      )}

      {/* ── Log entries ──────────────────────────────────────── */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto"
        style={{ background: "#0c0a09" }}
      >
        {log.map((entry) => (
          <LogRow
            key={entry.id}
            entry={entry}
            expandedEsql={expandedEsql}
            onToggleEsql={(id) => setExpandedEsql(expandedEsql === id ? null : id)}
          />
        ))}

        {/* ── Processing spinner ──────────────────────────────── */}
        {loading && (
          <div className="flex items-baseline gap-3 px-3 py-2 border-b border-stone-900">
            <span className="text-[9px] text-stone-600 w-16 shrink-0">
              {fmtTime(new Date())}
            </span>
            <span className="text-[9px] text-lime-600 w-[68px] shrink-0">AUDITOR-3</span>
            <span className="flex gap-1 items-center">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="w-1 h-1 rounded-full bg-lime-600"
                  style={{ animation: `dot-flash 1.2s ease-in-out ${i * 0.2}s infinite` }}
                />
              ))}
              <span className="text-[9px] text-stone-600 ml-2">PROCESSING QUERY...</span>
            </span>
          </div>
        )}
      </div>

      {/* ── Command input ─────────────────────────────────────── */}
      <div className="shrink-0 border-t border-stone-800 bg-stone-900">
        {/* Prompt line */}
        <div className="flex items-start gap-2 px-3 py-2">
          <div className="flex flex-col items-start gap-0.5 shrink-0 pt-0.5">
            <span className="text-[9px] text-stone-600 whitespace-nowrap">OPERATOR</span>
            <span className="text-lime-400 text-[11px]">›</span>
          </div>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder='query: "why vendor C?" | "current VAR?" | "active reroutes?"'
            rows={2}
            className="flex-1 resize-none bg-transparent text-[11px] text-stone-300
                       placeholder-stone-700 outline-none leading-relaxed
                       border-none focus:ring-0"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="tac-btn-lime shrink-0 self-end px-2 py-1 disabled:opacity-30"
          >
            EXEC
          </button>
        </div>

        {/* Hint row */}
        <div className="flex items-center gap-3 px-3 pb-2">
          <span className="text-[8px] text-stone-700">ENTER to execute · SHIFT+ENTER for newline</span>
        </div>
      </div>
    </div>
  );
}

// ── Log Row ────────────────────────────────────────────────────────────────

function LogRow({
  entry,
  expandedEsql,
  onToggleEsql,
}: {
  entry: LogEntry;
  expandedEsql: string | null;
  onToggleEsql: (id: string) => void;
}) {
  const meta = ROLE_META[entry.role];
  const isSelected = expandedEsql === entry.id;

  return (
    <div
      className="border-b border-stone-900"
      style={{
        background: entry.role === "operator"
          ? "rgba(41,37,36,0.4)"
          : entry.role === "error"
          ? "rgba(220,38,38,0.06)"
          : "transparent",
      }}
    >
      {/* ── Primary log line ──────────────────────────────── */}
      <div className="flex items-start gap-3 px-3 py-2">
        {/* Timestamp */}
        <span className="text-[9px] text-stone-700 w-16 shrink-0 pt-px">
          {fmtTime(entry.ts)}
        </span>

        {/* Role identifier */}
        <span
          className="text-[9px] font-bold w-[68px] shrink-0 pt-px uppercase tracking-wide"
          style={{ color: meta.color }}
        >
          {meta.id}
        </span>

        {/* Body */}
        <div className="flex-1 min-w-0">
          {/* Operator: show prefix + text inline */}
          {entry.role === "operator" ? (
            <p className="text-[11px] text-stone-300 whitespace-pre-wrap leading-relaxed">
              {entry.text}
            </p>
          ) : (
            <>
              {/* System / Error: plain mono text */}
              <p
                className="text-[11px] leading-relaxed whitespace-pre-wrap"
                style={{ color: entry.role === "error" ? "#fca5a5" : "#a8a29e" }}
              >
                {entry.text}
              </p>

              {/* Structured KV block for agent decisions */}
              {entry.kvPairs && Object.keys(entry.kvPairs).length > 0 && (
                <div
                  className="mt-2 px-2 py-1.5 border-l-2 border-lime-800"
                  style={{ background: "rgba(2,44,34,0.35)" }}
                >
                  <div className="text-[8px] uppercase tracking-widest text-lime-800 mb-1">
                    DECISION METRICS
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                    {Object.entries(entry.kvPairs).map(([k, v]) => (
                      <div key={k} className="flex items-baseline gap-1.5">
                        <span className="text-[9px] text-stone-600 uppercase tracking-wide shrink-0">{k}:</span>
                        <span className="text-[10px] text-lime-400 font-bold truncate">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Highlighted entities */}
              {entry.highlightedEntities && entry.highlightedEntities.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {entry.highlightedEntities.map((e) => (
                    <span
                      key={e}
                      className="text-[9px] uppercase px-1.5 py-px border border-lime-900 text-lime-600"
                      style={{ borderRadius: "1px" }}
                    >
                      {e}
                    </span>
                  ))}
                </div>
              )}

              {/* ES|QL toggle */}
              {entry.esql && (
                <div className="mt-2">
                  <button
                    onClick={() => onToggleEsql(entry.id)}
                    className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider
                               text-stone-600 hover:text-stone-400 transition-colors duration-75"
                  >
                    <span
                      className="inline-block transition-transform duration-100"
                      style={{ transform: isSelected ? "rotate(90deg)" : "rotate(0deg)" }}
                    >
                      ▶
                    </span>
                    ES|QL SOURCE QUERY
                  </button>

                  {isSelected && (
                    <pre
                      data-selectable
                      className="mt-1.5 px-3 py-2 text-[10px] leading-relaxed overflow-x-auto
                                 border-l-2 border-stone-700"
                      style={{
                        background: "#0c0a09",
                        color: "#a3e635",
                        fontFamily: "'JetBrains Mono', monospace",
                        whiteSpace: "pre",
                      }}
                    >
                      {entry.esql}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
