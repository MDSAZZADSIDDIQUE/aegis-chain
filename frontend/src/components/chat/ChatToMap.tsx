"use client";

import { useState, useRef, useEffect } from "react";
import { sendChatMessage, type ChatResponse } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "agent";
  text: string;
  esql?: string | null;
  highlightedEntities?: string[];
  timestamp: Date;
}

interface ChatToMapProps {
  contextThreatId?: string;
  onHighlight: (entities: string[]) => void;
}

export default function ChatToMap({ contextThreatId, onHighlight }: ChatToMapProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "agent",
      text: 'AegisChain Auditor online. Ask me anything about supplier decisions, threat assessments, or active reroutes. Try: "Why did you choose this vendor?" or "What is the current value at risk?"',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [showEsql, setShowEsql] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const question = input.trim();
    if (!question || loading) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: "user",
      text: question,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res: ChatResponse = await sendChatMessage(question, contextThreatId);

      const agentMsg: Message = {
        id: `a-${Date.now()}`,
        role: "agent",
        text: res.answer,
        esql: res.esql_query,
        highlightedEntities: res.highlighted_entities,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, agentMsg]);

      if (res.highlighted_entities?.length) {
        onHighlight(res.highlighted_entities);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "agent",
          text: "Connection error. Ensure the backend is running on localhost:8000.",
          timestamp: new Date(),
        },
      ]);
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
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerDot} />
        <span style={styles.headerTitle}>Chat-to-Map</span>
        <span style={styles.headerBadge}>ES|QL</span>
      </div>

      {/* Messages */}
      <div ref={scrollRef} style={styles.messages}>
        {messages.map((msg) => (
          <div key={msg.id} style={msg.role === "user" ? styles.userBubble : styles.agentBubble}>
            <div style={styles.bubbleHeader}>
              <span style={msg.role === "user" ? styles.roleUser : styles.roleAgent}>
                {msg.role === "user" ? "You" : "AegisChain"}
              </span>
              <span style={styles.time}>
                {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
            <div style={styles.bubbleText}>{msg.text}</div>

            {msg.esql && (
              <div style={styles.esqlToggle}>
                <button
                  onClick={() => setShowEsql(showEsql === msg.id ? null : msg.id)}
                  style={styles.esqlButton}
                >
                  {showEsql === msg.id ? "Hide" : "Show"} ES|QL Query
                </button>
                {showEsql === msg.id && (
                  <pre style={styles.esqlBlock}>{msg.esql}</pre>
                )}
              </div>
            )}

            {msg.highlightedEntities && msg.highlightedEntities.length > 0 && (
              <div style={styles.entityTags}>
                {msg.highlightedEntities.map((e) => (
                  <span key={e} style={styles.entityTag}>{e}</span>
                ))}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={styles.agentBubble}>
            <div style={styles.loadingDots}>
              <span style={styles.dot} /><span style={styles.dot} /><span style={styles.dot} />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div style={styles.inputArea}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder='Ask: "Why did you choose Vendor C over Vendor A?"'
          style={styles.textarea}
          rows={1}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          style={{
            ...styles.sendButton,
            opacity: loading || !input.trim() ? 0.4 : 1,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    background: "#111827",
    borderLeft: "1px solid #2a3040",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "12px 16px",
    borderBottom: "1px solid #2a3040",
    background: "#0f1420",
  },
  headerDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: "#22c55e",
    boxShadow: "0 0 6px #22c55e",
  },
  headerTitle: {
    fontWeight: 600,
    fontSize: 14,
    color: "#e2e8f0",
    flex: 1,
  },
  headerBadge: {
    fontSize: 10,
    fontWeight: 600,
    padding: "2px 6px",
    borderRadius: 4,
    background: "#1e293b",
    color: "#06b6d4",
    fontFamily: "'JetBrains Mono', monospace",
  },
  messages: {
    flex: 1,
    overflowY: "auto" as const,
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  userBubble: {
    alignSelf: "flex-end",
    maxWidth: "85%",
    background: "#1e3a5f",
    borderRadius: "12px 12px 4px 12px",
    padding: "10px 14px",
  },
  agentBubble: {
    alignSelf: "flex-start",
    maxWidth: "85%",
    background: "#1a1f2e",
    borderRadius: "12px 12px 12px 4px",
    padding: "10px 14px",
    border: "1px solid #2a3040",
  },
  bubbleHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  roleUser: { fontSize: 11, fontWeight: 600, color: "#60a5fa" },
  roleAgent: { fontSize: 11, fontWeight: 600, color: "#22c55e" },
  time: { fontSize: 10, color: "#64748b" },
  bubbleText: {
    fontSize: 13,
    lineHeight: "1.5",
    color: "#e2e8f0",
    whiteSpace: "pre-wrap" as const,
  },
  esqlToggle: { marginTop: 8 },
  esqlButton: {
    fontSize: 11,
    color: "#06b6d4",
    background: "none",
    border: "1px solid #164e63",
    borderRadius: 4,
    padding: "3px 8px",
    cursor: "pointer",
    fontFamily: "'JetBrains Mono', monospace",
  },
  esqlBlock: {
    marginTop: 6,
    padding: 10,
    background: "#0f1420",
    border: "1px solid #2a3040",
    borderRadius: 6,
    fontSize: 11,
    color: "#06b6d4",
    fontFamily: "'JetBrains Mono', monospace",
    overflowX: "auto" as const,
    whiteSpace: "pre" as const,
    lineHeight: "1.4",
  },
  entityTags: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: 4,
    marginTop: 8,
  },
  entityTag: {
    fontSize: 10,
    padding: "2px 8px",
    borderRadius: 10,
    background: "#1e293b",
    color: "#f59e0b",
    border: "1px solid #92400e",
  },
  inputArea: {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
    padding: "12px 16px",
    borderTop: "1px solid #2a3040",
    background: "#0f1420",
  },
  textarea: {
    flex: 1,
    resize: "none" as const,
    background: "#111827",
    border: "1px solid #2a3040",
    borderRadius: 8,
    padding: "10px 12px",
    fontSize: 13,
    color: "#e2e8f0",
    fontFamily: "Inter, sans-serif",
    outline: "none",
    lineHeight: "1.4",
  },
  sendButton: {
    width: 38,
    height: 38,
    borderRadius: 8,
    border: "none",
    background: "#3b82f6",
    color: "#ffffff",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  loadingDots: {
    display: "flex",
    gap: 4,
    padding: "4px 0",
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "#64748b",
    animation: "pulse 1.4s infinite ease-in-out",
  },
};
