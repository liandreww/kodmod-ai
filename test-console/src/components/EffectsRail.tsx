"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Card, Collapsible, Copy, Empty, Field, Spinner, Json } from "@/components/ui";
import { callConsole } from "@/lib/client";

export function EffectsRail({
  sessionId,
  onSessionChange,
  extra,
}: {
  sessionId: string;
  onSessionChange?: (v: string) => void;
  extra?: ReactNode;
}) {
  const [redis, setRedis] = useState<{ entries: { key: string; type: string; ttl: number; value: unknown }[] } | null>(null);
  const [trace, setTrace] = useState<{ available: boolean; steps?: unknown[]; interrupted?: boolean; reason?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const [r, t] = await Promise.all([
        callConsole<{ entries: { key: string; type: string; ttl: number; value: unknown }[] }>(
          `/api/redis/keys?pattern=${encodeURIComponent(`kodmod:session:${sessionId}:*`)}&values=1`,
        ),
        callConsole<{ available: boolean; steps?: unknown[]; interrupted?: boolean; reason?: string }>(
          `/api/checkpoints?thread=${encodeURIComponent(sessionId)}`,
        ),
      ]);
      setRedis(r);
      setTrace(t);
    } finally {
      setBusy(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div>
      <Card
        title="Session"
        icon="bi-fingerprint"
        actions={
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={refresh} disabled={!sessionId || busy}>
            <i className="bi bi-arrow-clockwise" aria-hidden="true" />
            <span className="ms-1">
              <Spinner show={busy} />
            </span>
          </button>
        }
      >
        <Field label="session_id" hint="= LangGraph thread_id">
          <div className="input-group input-group-sm">
            <input
              className="form-control mono"
              value={sessionId}
              placeholder="starts after the first turn"
              onChange={(e) => onSessionChange?.(e.target.value)}
              readOnly={!onSessionChange}
            />
            {sessionId && <Copy value={sessionId} />}
          </div>
        </Field>
        {sessionId && (
          <Link href={`/graph?thread=${encodeURIComponent(sessionId)}`} className="btn btn-sm btn-outline-primary mt-2 w-100">
            <i className="bi bi-diagram-3 me-1" aria-hidden="true" />
            Open graph trace
          </Link>
        )}
      </Card>

      <Card title="Redis short-term memory" icon="bi-hdd-stack">
        {!sessionId ? (
          <Empty icon="bi-hdd">No session yet</Empty>
        ) : !redis?.entries.length ? (
          <div className="small text-secondary">
            No <span className="mono">kodmod:session:{sessionId.slice(0, 8)}...</span> keys. Only the quiz path writes
            Redis today: <code>store_quiz_session</code> from the problem generator and student model.{" "}
            <code>store_last_response</code>, <code>append_tutoring_turn</code> and <code>set_pacing</code> exist in{" "}
            <code>memory/short_term.py</code> but nothing calls them, so a tutoring turn leaves Redis untouched.
          </div>
        ) : (
          redis.entries.map((e) => (
            <Collapsible
              key={e.key}
              summary={<span className="mono">{e.key.split(":").slice(3).join(":")}</span>}
              badge={
                <span className="d-flex gap-1">
                  <span className="badge bg-secondary">{e.type}</span>
                  <span className="badge bg-light text-dark" title="TTL seconds">
                    {e.ttl}s
                  </span>
                </span>
              }
            >
              <Json value={e.value} />
            </Collapsible>
          ))
        )}
      </Card>

      <Card title="Graph checkpoints" icon="bi-diagram-3">
        {!trace ? (
          <Empty icon="bi-diagram-3">No session yet</Empty>
        ) : !trace.available ? (
          <div className="alert alert-warning py-2 px-2 small mb-0">{trace.reason}</div>
        ) : !trace.steps?.length ? (
          <div className="small text-secondary">
            No checkpoints for this thread. If the turn just ran, the API is using the in-memory checkpointer
            (<code>KODMOD_CHECKPOINTER=memory</code>) and persists nothing.
          </div>
        ) : (
          <>
            <div className="d-flex gap-2 align-items-center">
              <span className="badge bg-primary">{trace.steps.length} steps</span>
              {trace.interrupted && (
                <span className="badge bg-warning text-dark" title="interrupt_after=['reflection']">
                  interrupted
                </span>
              )}
            </div>
            <div className="d-flex flex-wrap gap-1 mt-2">
              {(trace.steps as { nodes: string[] }[]).flatMap((s, i) =>
                s.nodes.map((n) => (
                  <span key={`${i}-${n}`} className="badge bg-secondary">
                    {n}
                  </span>
                )),
              )}
            </div>
          </>
        )}
      </Card>

      {extra}
    </div>
  );
}
