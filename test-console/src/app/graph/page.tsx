"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, Collapsible, ConfirmButton, Copy, Empty, ErrorNote, Json, Spinner } from "@/components/ui";
import { callConsole } from "@/lib/client";
import { changedOnly, diffObjects, type FieldChange } from "@/lib/diff";

interface Task {
  taskId: string;
  node: string;
  taskPath: string | null;
  output: Record<string, unknown>;
}

interface Step {
  checkpointId: string;
  parentCheckpointId: string | null;
  ns: string;
  ts: string | null;
  step: number | null;
  source: string | null;
  nodes: string[];
  producedBy: Task[];
  scheduled: Task[];
  state: Record<string, unknown>;
  metadata: Record<string, unknown>;
  versionsSeen: Record<string, unknown>;
}

interface TraceResponse {
  available: boolean;
  reason?: string;
  threadId?: string;
  steps?: Step[];
  nodeOrder?: string[];
  interrupted?: boolean;
  pausedAfter?: string | null;
  interruptNode?: string;
  counts?: Record<string, number>;
  threads?: { thread_id: string; steps: number; first_ts: string; last_ts: string }[];
}

export default function GraphPage() {
  const [thread, setThread] = useState("");
  const [threads, setThreads] = useState<TraceResponse["threads"]>([]);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [onlyChanged, setOnlyChanged] = useState(true);

  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("thread");
    if (fromUrl) setThread(fromUrl);
  }, []);

  const loadThreads = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await callConsole<TraceResponse>("/api/checkpoints");
      if (!res.available) {
        setTrace(res);
        setThreads([]);
      } else {
        setThreads(res.threads ?? []);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const loadTrace = useCallback(async (id: string) => {
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const res = await callConsole<TraceResponse>(`/api/checkpoints?thread=${encodeURIComponent(id)}`);
      setTrace(res);
      setSelected(Math.max(0, (res.steps?.length ?? 1) - 1));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (thread) void loadTrace(thread);
  }, [thread, loadTrace]);

  const steps = trace?.steps ?? [];
  const current = steps[selected];
  const previous = selected > 0 ? steps[selected - 1] : null;

  const changes: FieldChange[] = useMemo(() => {
    if (!current) return [];
    const all = diffObjects(previous?.state ?? {}, current.state);
    return onlyChanged ? changedOnly(all) : all;
  }, [current, previous, onlyChanged]);

  const path = useMemo(() => steps.flatMap((s) => s.nodes), [steps]);

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Graph trace</h5>
        <div className="d-flex align-items-center gap-2">
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={loadThreads} disabled={busy}>
            <i className="bi bi-arrow-clockwise me-1" aria-hidden="true" />
            Threads
          </button>
          {thread && (
            <>
              <button
                type="button"
                className="btn btn-sm btn-outline-primary"
                onClick={() => loadTrace(thread)}
                disabled={busy}
              >
                <i className="bi bi-arrow-repeat me-1" aria-hidden="true" />
                Reload trace
              </button>
              <ConfirmButton
                label="Purge thread"
                icon="bi-trash"
                message={`Delete every checkpoint, blob and write row for thread ${thread}. The conversation state for that session is lost.`}
                onConfirm={async () => {
                  await fetch(`/api/checkpoints?thread=${encodeURIComponent(thread)}`, { method: "DELETE" });
                  setTrace(null);
                  setThread("");
                  await loadThreads();
                }}
              />
            </>
          )}
        </div>
      </div>

      <ErrorNote error={error} />

      {trace && !trace.available && (
        <div className="alert alert-warning d-flex gap-2 align-items-start" role="alert">
          <i className="bi bi-exclamation-triangle-fill mt-1" aria-hidden="true" />
          <div>
            <div className="fw-semibold">Graph trace unavailable</div>
            <div className="small">{trace.reason}</div>
          </div>
        </div>
      )}

      <div className="split">
        <div>
          <Card title="Thread" icon="bi-hash">
            <div className="input-group input-group-sm mb-2">
              <input
                className="form-control mono"
                placeholder="thread_id (session_id or quiz_session_id)"
                value={thread}
                onChange={(e) => setThread(e.target.value)}
              />
              {thread && <Copy value={thread} />}
              <button type="button" className="btn btn-outline-primary" onClick={() => loadTrace(thread)} disabled={busy}>
                Load
              </button>
            </div>

            {!!threads?.length && (
              <select
                className="form-select form-select-sm mono"
                value={thread}
                onChange={(e) => setThread(e.target.value)}
                size={Math.min(8, threads.length)}
              >
                {threads.map((t) => (
                  <option key={t.thread_id} value={t.thread_id}>
                    {t.thread_id} · {t.steps} steps · {String(t.last_ts ?? "").slice(0, 19)}
                  </option>
                ))}
              </select>
            )}
          </Card>

          {steps.length > 0 && (
            <>
              <Card title="Node path" icon="bi-signpost-split">
                <div className="d-flex flex-wrap gap-1 align-items-center">
                  {path.length === 0 ? (
                    <span className="text-secondary small">
                      No node writes recorded on this thread — only input checkpoints.
                    </span>
                  ) : (
                    path.map((n, i) => (
                      <span key={`${n}-${i}`} className="d-flex align-items-center gap-1">
                        <span
                          className={`badge ${
                            n === "__start__"
                              ? "bg-secondary"
                              : n === trace?.interruptNode
                                ? "bg-warning text-dark"
                                : "bg-primary"
                          }`}
                        >
                          {n}
                        </span>
                        {i < path.length - 1 && <i className="bi bi-chevron-right text-secondary small" aria-hidden="true" />}
                      </span>
                    ))
                  )}
                </div>

                {trace?.interrupted && (
                  <div className="alert alert-warning py-1 px-2 small mt-2 mb-0">
                    The last checkpoint still has unapplied writes
                    {trace.pausedAfter ? ` after ${trace.pausedAfter}` : ""}. The graph compiles with{" "}
                    <code>interrupt_after=[&quot;{trace.interruptNode}&quot;]</code> whenever a checkpointer is present;
                    callers resume with <code>ainvoke(None, config)</code>.
                  </div>
                )}

                {trace?.counts && (
                  <div className="d-flex gap-2 mt-2">
                    {Object.entries(trace.counts).map(([k, v]) => (
                      <span key={k} className="badge bg-light text-dark mono">
                        {k} {v}
                      </span>
                    ))}
                  </div>
                )}
              </Card>

              <Card title="Steps" icon="bi-list-ol" bodyClass="card-body p-0">
                <div className="list-group list-group-flush step-rail">
                  {steps.map((s, i) => (
                    <button
                      key={s.checkpointId}
                      type="button"
                      className={`list-group-item list-group-item-action py-2 ${i === selected ? "active" : ""}`}
                      onClick={() => setSelected(i)}
                    >
                      <div className="d-flex align-items-center gap-2 flex-wrap">
                        <span className="badge bg-secondary">step {String(s.step ?? i)}</span>
                        <span className="badge bg-light text-dark">{s.source}</span>
                        {s.nodes.length === 0 && <span className="small text-secondary">initial</span>}
                        {s.nodes.map((n) => (
                          <span key={n} className={`badge ${i === selected ? "bg-light text-dark" : "bg-primary"}`}>
                            {n}
                          </span>
                        ))}
                        {s.scheduled.length > 0 && (
                          <span className="badge bg-warning text-dark" title="writes not applied yet">
                            {s.scheduled.map((t) => t.node).join(", ")} pending
                          </span>
                        )}
                        <span className="ms-auto small mono">{String(s.ts ?? "").slice(11, 23)}</span>
                      </div>
                      <div className="small mono opacity-75">{s.checkpointId}</div>
                    </button>
                  ))}
                </div>
              </Card>
            </>
          )}

          {trace?.available && thread && steps.length === 0 && !busy && (
            <div className="alert alert-warning py-2 px-3 small" role="alert">
              <div className="fw-semibold mb-1">No checkpoints for this thread</div>
              Either the thread id is wrong, or the API is running with{" "}
              <code>KODMOD_CHECKPOINTER=memory</code>, which keeps graph state in process and writes nothing to
              Postgres. Older rows from a previous run stay in the table, so a populated thread list does not prove the
              current server is recording. Restart the API without that variable
              (<code>make compose-test-up-api</code> uses the Postgres saver;{" "}
              <code>make compose-test-up-api-perf</code> does not).
            </div>
          )}
        </div>

        <div>
          {current ? (
            <>
              <Card
                title={
                  current.nodes.length
                    ? `Returned by ${current.nodes.join(", ")}`
                    : `Step ${current.step ?? selected} input`
                }
                icon="bi-box-arrow-in-down"
                bodyClass="card-body p-2"
              >
                {current.producedBy.length === 0 ? (
                  <Empty icon="bi-dash-circle">Nothing was written into this checkpoint</Empty>
                ) : (
                  current.producedBy.map((task) => (
                    <div key={task.taskId} className="mb-2">
                      <div className="small mono text-secondary mb-1">{task.taskPath ?? task.taskId}</div>
                      {Object.keys(task.output).length === 0 ? (
                        <div className="small text-secondary">no state keys returned</div>
                      ) : (
                        Object.entries(task.output).map(([k, v]) => (
                          <Collapsible key={k} summary={<span className="mono">{k}</span>}>
                            <Json value={v} />
                          </Collapsible>
                        ))
                      )}
                    </div>
                  ))
                )}
              </Card>

              <Card
                title="Accumulated state"
                icon="bi-box"
                actions={
                  <div className="form-check form-switch mb-0">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      id="onlychanged"
                      checked={onlyChanged}
                      onChange={(e) => setOnlyChanged(e.target.checked)}
                    />
                    <label className="form-check-label small" htmlFor="onlychanged">
                      changed only
                    </label>
                  </div>
                }
                bodyClass="card-body p-2"
              >
                {changes.length === 0 ? (
                  <Empty icon="bi-dash-circle">No field changed at this step</Empty>
                ) : (
                  changes.map((c) => (
                    <Collapsible
                      key={c.key}
                      summary={<span className="mono">{c.key}</span>}
                      badge={
                        <span
                          className={`badge ${
                            c.kind === "added"
                              ? "bg-success"
                              : c.kind === "removed"
                                ? "bg-danger"
                                : c.kind === "changed"
                                  ? "bg-warning text-dark"
                                  : "bg-light text-dark"
                          }`}
                        >
                          {c.kind}
                        </span>
                      }
                    >
                      {c.kind === "changed" && (
                        <>
                          <div className="small text-secondary">before</div>
                          <Json value={c.before} />
                        </>
                      )}
                      <div className="small text-secondary mt-1">{c.kind === "removed" ? "removed value" : "value"}</div>
                      <Json value={c.kind === "removed" ? c.before : c.after} />
                    </Collapsible>
                  ))
                )}
              </Card>

              {current.scheduled.length > 0 && (
                <Card title="Pending writes" icon="bi-hourglass-split" bodyClass="card-body p-2">
                  <div className="small text-secondary mb-2">
                    Produced by the next task but not yet folded into a checkpoint — this is what an interrupt looks
                    like on disk.
                  </div>
                  {current.scheduled.map((t) => (
                    <Collapsible
                      key={t.taskId}
                      summary={<span className="mono">{t.node || t.taskId}</span>}
                      badge={<span className="badge bg-warning text-dark">{Object.keys(t.output).length} keys</span>}
                    >
                      <Json value={t.output} />
                    </Collapsible>
                  ))}
                </Card>
              )}

              <Card title="Checkpoint metadata" icon="bi-info-circle">
                <Json value={{ ...current.metadata, versions_seen: current.versionsSeen }} />
              </Card>
            </>
          ) : (
            <Card title="State" icon="bi-box">
              {busy ? <Spinner show /> : <Empty icon="bi-box">Pick a thread and a step</Empty>}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
