"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Class error boundary wrapping <AegisGlobe>.
 * Catches Mapbox GL JS initialisation failures, WebGL unavailability,
 * and any render-time exceptions thrown inside the globe component tree.
 */
export default class GlobeErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[AegisGlobe] render error:", error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div
          className="w-full h-full flex flex-col items-center justify-center bg-stone-950 select-none"
          style={{ gap: "20px" }}
        >
          {/* Broken-signal icon */}
          <svg
            width="48"
            height="48"
            viewBox="0 0 48 48"
            fill="none"
            aria-hidden
          >
            <polygon
              points="24,4 44,16 44,32 24,44 4,32 4,16"
              stroke="#dc2626"
              strokeWidth="1.5"
              fill="none"
              strokeDasharray="4 3"
            />
            <line x1="16" y1="16" x2="32" y2="32" stroke="#dc2626" strokeWidth="1.5" />
            <line x1="32" y1="16" x2="16" y2="32" stroke="#dc2626" strokeWidth="1.5" />
          </svg>

          {/* Primary status line */}
          <div className="font-mono text-sm font-bold tracking-widest uppercase text-red-500">
            SATELLITE FEED UNAVAILABLE
          </div>

          {/* Error detail */}
          <div
            className="font-mono text-[10px] text-stone-500 text-center max-w-xs leading-relaxed px-4"
            style={{ wordBreak: "break-word" }}
          >
            {this.state.error.message || "Unknown render error"}
          </div>

          {/* Retry */}
          <button
            onClick={this.handleRetry}
            className="font-mono text-[10px] uppercase tracking-widest px-4 py-1.5 border border-stone-700 text-stone-400 hover:border-lime-600 hover:text-lime-400 transition-colors duration-150"
            style={{ borderRadius: "1px" }}
          >
            ↺ REINITIALISE FEED
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
