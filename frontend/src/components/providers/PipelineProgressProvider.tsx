"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  subscribePipelineProgress,
  type PipelineProgressEvent,
} from "@/lib/api";

/**
 * Shared pipeline-progress context.
 *
 * Opens a **single** WebSocket to `/ws/pipeline` at the provider level
 * and fans events out to every consumer via React context.  This replaces
 * the previous pattern where `page.tsx`, `PipelineTelemetry`, and
 * `ChatToMap` each opened their own connection (3× resource waste).
 */

interface PipelineProgressContextValue {
  /** The most recent event received from the WebSocket. */
  lastEvent: PipelineProgressEvent | null;
}

const PipelineProgressContext = createContext<PipelineProgressContextValue>({
  lastEvent: null,
});

export function usePipelineProgress(): PipelineProgressContextValue {
  return useContext(PipelineProgressContext);
}

export function PipelineProgressProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [lastEvent, setLastEvent] = useState<PipelineProgressEvent | null>(
    null,
  );

  // Reconnect on unmount/remount but never duplicate
  const closeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    closeRef.current = subscribePipelineProgress(
      (ev) => setLastEvent(ev),
      () => {
        // WS closed — could add reconnect logic here if desired
      },
    );
    return () => {
      closeRef.current?.();
      closeRef.current = null;
    };
  }, []);

  return (
    <PipelineProgressContext.Provider value={{ lastEvent }}>
      {children}
    </PipelineProgressContext.Provider>
  );
}
