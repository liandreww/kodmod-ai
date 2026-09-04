"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export interface ActivityEvent {
  id: number;
  ts: string;
  source: string;
  level: "info" | "warn" | "error";
  label: string;
  durationMs?: number;
  detail?: unknown;
}

interface ActivityContextValue {
  events: ActivityEvent[];
  connected: boolean;
  paused: boolean;
  setPaused: (v: boolean) => void;
  clear: () => void;
  /** Highest event id seen so far; used to mark "what happened since". */
  cursor: number;
}

const ActivityContext = createContext<ActivityContextValue>({
  events: [],
  connected: false,
  paused: false,
  setPaused: () => undefined,
  clear: () => undefined,
  cursor: 0,
});

const MAX_EVENTS = 4000;

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const pending = useRef<ActivityEvent[]>([]);

  useEffect(() => {
    pausedRef.current = paused;
    if (!paused && pending.current.length) {
      const buffered = pending.current;
      pending.current = [];
      setEvents((prev) => [...prev, ...buffered].slice(-MAX_EVENTS));
    }
  }, [paused]);

  useEffect(() => {
    const source = new EventSource("/api/stream/activity");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as ActivityEvent;
        if (pausedRef.current) {
          pending.current.push(ev);
          if (pending.current.length > MAX_EVENTS) pending.current.splice(0, pending.current.length - MAX_EVENTS);
          return;
        }
        setEvents((prev) => (prev.some((p) => p.id === ev.id) ? prev : [...prev, ev].slice(-MAX_EVENTS)));
      } catch {
        /* ignore malformed frame */
      }
    };
    return () => source.close();
  }, []);

  const clear = useCallback(() => {
    pending.current = [];
    setEvents([]);
    void fetch("/api/tap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ tap: "clear" }),
    });
  }, []);

  const cursor = events.length ? events[events.length - 1].id : 0;

  const value = useMemo(
    () => ({ events, connected, paused, setPaused, clear, cursor }),
    [events, connected, paused, clear, cursor],
  );

  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

export function useActivity() {
  return useContext(ActivityContext);
}

export const SOURCE_LABELS: Record<string, string> = {
  http: "HTTP",
  sql: "SQL tap",
  "console-sql": "SQL (console)",
  redis: "Redis tap",
  "console-redis": "Redis (console)",
  ws: "WebSocket",
  proc: "Script",
  apilog: "api.log",
  system: "System",
};

export function sourceClass(source: string): string {
  switch (source) {
    case "http": return "text-primary";
    case "sql": return "text-success";
    case "console-sql": return "text-success-emphasis";
    case "redis": return "text-danger";
    case "console-redis": return "text-danger-emphasis";
    case "ws": return "text-info-emphasis";
    case "proc": return "text-warning-emphasis";
    case "apilog": return "text-body-secondary";
    default: return "text-secondary";
  }
}

export function LogList({
  events,
  height = "100%",
}: {
  events: ActivityEvent[];
  height?: string;
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);

  useEffect(() => {
    if (stick) endRef.current?.scrollIntoView({ block: "end" });
  }, [events.length, stick]);

  return (
    <div
      className="log-list border rounded"
      style={{ height }}
      onScroll={(e) => {
        const el = e.currentTarget;
        setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
      }}
    >
      {events.map((e) => (
        <div key={e.id}>
          <div className="log-row" onClick={() => setOpenId(openId === e.id ? null : e.id)}>
            <span className="text-secondary">{e.ts.slice(11, 19)}</span>
            <span className={sourceClass(e.source)}>{SOURCE_LABELS[e.source] ?? e.source}</span>
            <span
              className={`log-msg ${e.level === "error" ? "text-danger" : e.level === "warn" ? "text-warning-emphasis" : ""}`}
            >
              {e.label}
            </span>
            <span className="text-secondary">{e.durationMs !== undefined ? `${e.durationMs}ms` : ""}</span>
          </div>
          {openId === e.id && e.detail !== undefined && (
            <pre className="out mb-0" style={{ borderRadius: 0 }}>
              {typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail, null, 2)}
            </pre>
          )}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
