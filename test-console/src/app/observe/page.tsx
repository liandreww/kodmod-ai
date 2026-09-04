"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LogList, SOURCE_LABELS, useActivity } from "@/components/activity";
import { Card, StatusDot } from "@/components/ui";

interface TapStatus {
  sql: { running: boolean; mode: string | null; profile: string | null };
  redis: { running: boolean };
  apilog: { running: boolean; file: string };
}

const TAP_INFO: Record<string, { title: string; icon: string; detail: string }> = {
  sql: {
    title: "Postgres statements",
    icon: "bi-database-fill-gear",
    detail:
      "Sets log_statement='all' and log_line_prefix with the application name via ALTER SYSTEM + pg_reload_conf(), then streams the container log. Captures every query the backend issues, including the LangGraph checkpointer's separate psycopg pool. Falls back to polling pg_stat_activity when Docker is unreachable.",
  },
  redis: {
    title: "Redis commands",
    icon: "bi-hdd-network",
    detail: "Opens a dedicated MONITOR connection and streams every command the backend sends.",
  },
  apilog: {
    title: "Backend log file",
    icon: "bi-file-text",
    detail:
      "Tails kodmod-ai/reports/api.log, written when the API is started through scripts/serve_test_api. Route-level log.warning calls do not reach this file.",
  },
};

const ALL_SOURCES = [
  "http",
  "sql",
  "console-sql",
  "redis",
  "console-redis",
  "ws",
  "proc",
  "apilog",
  "system",
];

export default function ObservePage() {
  const { events, connected, paused, setPaused, clear } = useActivity();
  const [taps, setTaps] = useState<TapStatus | null>(null);
  const [sources, setSources] = useState<Set<string>>(new Set(ALL_SOURCES));
  const [levels, setLevels] = useState<Set<string>>(new Set(["info", "warn", "error"]));
  const [search, setSearch] = useState("");
  const [busyTap, setBusyTap] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setTaps(await (await fetch("/api/tap", { cache: "no-store" })).json());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (tap: string, on: boolean) => {
    setBusyTap(tap);
    try {
      const res = await fetch("/api/tap", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tap, on }),
      });
      setTaps(await res.json());
    } finally {
      setBusyTap(null);
    }
  };

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return events.filter((e) => {
      if (!sources.has(e.source)) return false;
      if (!levels.has(e.level)) return false;
      if (needle && !e.label.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [events, sources, levels, search]);

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const e of events) out[e.source] = (out[e.source] ?? 0) + 1;
    return out;
  }, [events]);

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `kodmod-activity-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const toggleSet = (set: Set<string>, value: string, apply: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    apply(next);
  };

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Live activity</h5>
        <span className="d-flex align-items-center gap-2 small">
          <StatusDot state={connected ? "ok" : "bad"} />
          {connected ? "stream connected" : "stream disconnected"}
        </span>
      </div>

      <div className="row g-3 mb-3">
        {(["sql", "redis", "apilog"] as const).map((t) => {
          const info = TAP_INFO[t];
          const running = taps?.[t]?.running ?? false;
          return (
            <div className="col-md-4" key={t}>
              <div className={`card h-100 ${running ? "border-success" : ""}`}>
                <div className="card-body py-2">
                  <div className="d-flex align-items-center gap-2 mb-1">
                    <i className={`bi ${info.icon}`} aria-hidden="true" />
                    <span className="fw-semibold">{info.title}</span>
                    <span className="badge bg-secondary ms-auto">{counts[t] ?? 0}</span>
                  </div>
                  <div className="form-check form-switch mb-1">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      id={`tap-${t}`}
                      checked={running}
                      disabled={busyTap === t}
                      onChange={(e) => toggle(t, e.target.checked)}
                    />
                    <label className="form-check-label small" htmlFor={`tap-${t}`}>
                      {running ? "on" : "off"}
                    </label>
                    {busyTap === t && <span className="spinner-border spinner-border-sm ms-2" role="status" />}
                  </div>
                  {t === "sql" && taps?.sql.mode && (
                    <div className="small mono text-secondary">{taps.sql.mode}</div>
                  )}
                  {t === "apilog" && taps?.apilog.file && (
                    <div className="small mono text-secondary text-truncate" title={taps.apilog.file}>
                      {taps.apilog.file}
                    </div>
                  )}
                  <details className="small mt-1">
                    <summary className="text-secondary">what this does</summary>
                    <div className="mt-1">{info.detail}</div>
                  </details>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {taps?.sql.running && (
        <div className="alert alert-warning py-1 px-2 small d-flex gap-2 align-items-center">
          <i className="bi bi-exclamation-triangle" aria-hidden="true" />
          <span>
            The SQL tap changed a server setting. Turning it off runs{" "}
            <code>ALTER SYSTEM RESET log_statement</code> and reloads the config.
          </span>
        </div>
      )}

      <Card
        title="Timeline"
        icon="bi-activity"
        actions={
          <>
            <input
              className="form-control form-control-sm"
              style={{ width: 220 }}
              placeholder="Filter text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button
              type="button"
              className={`btn btn-sm ${paused ? "btn-warning" : "btn-outline-secondary"}`}
              onClick={() => setPaused(!paused)}
              title={paused ? "Resume" : "Pause"}
            >
              <i className={`bi ${paused ? "bi-play-fill" : "bi-pause-fill"}`} aria-hidden="true" />
            </button>
            <button type="button" className="btn btn-sm btn-outline-secondary" onClick={exportJson} title="Export JSON">
              <i className="bi bi-download" aria-hidden="true" />
            </button>
            <button type="button" className="btn btn-sm btn-outline-danger" onClick={clear} title="Clear">
              <i className="bi bi-eraser" aria-hidden="true" />
            </button>
          </>
        }
        bodyClass="card-body p-2"
      >
        <div className="d-flex flex-wrap gap-1 mb-2">
          {ALL_SOURCES.map((s) => (
            <button
              key={s}
              type="button"
              className={`btn btn-sm py-0 ${sources.has(s) ? "btn-secondary" : "btn-outline-secondary"}`}
              onClick={() => toggleSet(sources, s, setSources)}
            >
              {SOURCE_LABELS[s] ?? s}
              <span className="badge bg-light text-dark ms-1">{counts[s] ?? 0}</span>
            </button>
          ))}
          <span className="vr mx-1" />
          {["info", "warn", "error"].map((l) => (
            <button
              key={l}
              type="button"
              className={`btn btn-sm py-0 ${levels.has(l) ? "btn-secondary" : "btn-outline-secondary"}`}
              onClick={() => toggleSet(levels, l, setLevels)}
            >
              {l}
            </button>
          ))}
          <span className="ms-auto small text-secondary align-self-center">
            {filtered.length} / {events.length}
          </span>
        </div>

        <LogList events={filtered} height="calc(100vh - 430px)" />
      </Card>
    </>
  );
}
