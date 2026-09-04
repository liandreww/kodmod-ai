"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, Collapsible, ConfirmButton, Empty, ErrorNote, Field, Json, Spinner } from "@/components/ui";
import { callConsole } from "@/lib/client";

interface Entry {
  key: string;
  type: string;
  ttl: number;
  size: number;
  value: unknown;
}

interface KeysResponse {
  pattern: string;
  entries: Entry[];
  sessions: { sessionId: string; subs: string[] }[];
}

const PATTERNS = ["kodmod:*", "kodmod:session:*", "kodmod:session:*:quiz", "kodmod:session:*:tutoring_turns", "*"];

/** memory/short_term.py:50 -- kodmod:session:{session_id}:{sub}, 24h TTL. */
const SUB_NOTES: Record<string, string> = {
  last_response: "JSON string. Written by the accessibility node so 'ulangi' can replay the last answer.",
  tutoring_turns: "List, RPUSH + LTRIM to the last 12 turns. The tutor's conversational window.",
  tts_rate: "String float. Pacing, falls back to settings.TTS_RATE.",
  quiz: "JSON string. Mid-quiz state the intent router rehydrates to force intent=quiz.",
};

export default function RedisPage() {
  const [pattern, setPattern] = useState("kodmod:*");
  const [data, setData] = useState<KeysResponse | null>(null);
  const [selected, setSelected] = useState<Entry | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await callConsole<KeysResponse & { error?: string }>(
        `/api/redis/keys?pattern=${encodeURIComponent(pattern)}&values=1`,
      );
      if (res.error) setError(res.error);
      else setData(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [pattern]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [autoRefresh, load]);

  const act = async (payload: Record<string, unknown>) => {
    setBusy(true);
    const res = await callConsole<{ error?: string }>("/api/redis/keys", { json: payload });
    if (res.error) setError(res.error);
    setSelected(null);
    await load();
  };

  const grouped = data?.sessions ?? [];
  const other = (data?.entries ?? []).filter((e) => !/^kodmod:session:[^:]+:/.test(e.key));

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Redis</h5>
        <div className="d-flex align-items-center gap-2">
          <div className="form-check form-switch mb-0">
            <input
              className="form-check-input"
              type="checkbox"
              id="autoref"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <label className="form-check-label small" htmlFor="autoref">
              auto refresh
            </label>
          </div>
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={load} disabled={busy}>
            <i className="bi bi-arrow-clockwise" aria-hidden="true" />
            <span className="ms-1">
              <Spinner show={busy} />
            </span>
          </button>
          <ConfirmButton
            label="Wipe kodmod:*"
            icon="bi-trash"
            message="Delete every key matching kodmod:* . Any in-progress quiz or tutoring window is lost, and the next turn starts from an empty short-term memory."
            onConfirm={() => act({ action: "deletePattern", pattern: "kodmod:*" })}
          />
        </div>
      </div>

      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card title="Scan" icon="bi-search">
            <div className="input-group input-group-sm mb-2">
              <input
                className="form-control mono"
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && load()}
              />
              <button type="button" className="btn btn-outline-primary" onClick={load}>
                SCAN
              </button>
            </div>
            <div className="d-flex flex-wrap gap-1">
              {PATTERNS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`btn btn-sm py-0 ${pattern === p ? "btn-secondary" : "btn-outline-secondary"}`}
                  onClick={() => setPattern(p)}
                >
                  <span className="mono">{p}</span>
                </button>
              ))}
            </div>
          </Card>

          {grouped.length === 0 && other.length === 0 ? (
            <Empty icon="bi-hdd">No keys match</Empty>
          ) : (
            <>
              {grouped.map((s) => {
                const entries = (data?.entries ?? []).filter((e) => e.key.startsWith(`kodmod:session:${s.sessionId}:`));
                return (
                  <Card
                    key={s.sessionId}
                    title={<span className="mono">{s.sessionId}</span>}
                    icon="bi-fingerprint"
                    actions={
                      <ConfirmButton
                        label="Clear session"
                        icon="bi-x-circle"
                        message={`Delete every key under kodmod:session:${s.sessionId}:* . The tutoring window, pacing, last response and any in-progress quiz for that session are lost.`}
                        onConfirm={() => act({ action: "deletePattern", pattern: `kodmod:session:${s.sessionId}:*` })}
                      />
                    }
                    bodyClass="card-body p-2"
                  >
                    {entries.map((e) => {
                      const sub = e.key.split(":").slice(3).join(":");
                      return (
                        <Collapsible
                          key={e.key}
                          summary={
                            <span>
                              <span className="mono">{sub}</span>
                              {SUB_NOTES[sub] && (
                                <i className="bi bi-info-circle ms-2 text-secondary" title={SUB_NOTES[sub]} />
                              )}
                            </span>
                          }
                          badge={
                            <span className="d-flex gap-1">
                              <span className="badge bg-secondary">{e.type}</span>
                              <span className="badge bg-light text-dark">{e.size}</span>
                              <span className="badge bg-light text-dark" title="TTL seconds">
                                {e.ttl}s
                              </span>
                            </span>
                          }
                        >
                          <Json value={e.value} />
                          <div className="d-flex gap-2 mt-2">
                            <button
                              type="button"
                              className="btn btn-sm btn-outline-secondary"
                              onClick={() => setSelected(e)}
                            >
                              <i className="bi bi-pencil me-1" aria-hidden="true" />
                              Edit
                            </button>
                            <ConfirmButton
                              label="Delete key"
                              icon="bi-trash"
                              message={`Delete ${e.key}.`}
                              onConfirm={() => act({ action: "delete", key: e.key })}
                            />
                          </div>
                        </Collapsible>
                      );
                    })}
                  </Card>
                );
              })}

              {other.length > 0 && (
                <Card title="Other keys" icon="bi-hdd" bodyClass="card-body p-2">
                  {other.map((e) => (
                    <Collapsible
                      key={e.key}
                      summary={<span className="mono">{e.key}</span>}
                      badge={
                        <span className="d-flex gap-1">
                          <span className="badge bg-secondary">{e.type}</span>
                          <span className="badge bg-light text-dark">{e.ttl}s</span>
                        </span>
                      }
                    >
                      <Json value={e.value} />
                      <div className="d-flex gap-2 mt-2">
                        <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setSelected(e)}>
                          <i className="bi bi-pencil me-1" aria-hidden="true" />
                          Edit
                        </button>
                        <ConfirmButton
                          label="Delete key"
                          icon="bi-trash"
                          message={`Delete ${e.key}.`}
                          onConfirm={() => act({ action: "delete", key: e.key })}
                        />
                      </div>
                    </Collapsible>
                  ))}
                </Card>
              )}
            </>
          )}
        </div>

        <div>
          {selected ? (
            <EditKey entry={selected} onClose={() => setSelected(null)} onSave={act} />
          ) : (
            <Card title="Key shapes" icon="bi-info-circle">
              <table className="table table-sm small mb-0">
                <tbody>
                  {Object.entries(SUB_NOTES).map(([k, v]) => (
                    <tr key={k}>
                      <td className="mono text-nowrap">{k}</td>
                      <td>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function EditKey({
  entry,
  onClose,
  onSave,
}: {
  entry: Entry;
  onClose: () => void;
  onSave: (p: Record<string, unknown>) => Promise<void>;
}) {
  const [value, setValue] = useState(
    typeof entry.value === "string" ? entry.value : JSON.stringify(entry.value, null, 2),
  );
  const [ttl, setTtl] = useState(entry.ttl > 0 ? entry.ttl : 86400);

  return (
    <Card
      title="Edit key"
      icon="bi-pencil-square"
      actions={<button type="button" className="btn-close" aria-label="Close" onClick={onClose} />}
    >
      <div className="mono small text-secondary mb-2 text-break">{entry.key}</div>
      {entry.type !== "string" && (
        <div className="alert alert-warning py-1 px-2 small">
          Only string keys can be rewritten here. Saving a {entry.type} key replaces it with a string.
        </div>
      )}
      <Field label="value">
        <textarea className="form-control form-control-sm mono" rows={12} value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      <Field label="ttl seconds" hint="0 = no expiry" className="mt-2">
        <input type="number" className="form-control form-control-sm" value={ttl} onChange={(e) => setTtl(Number(e.target.value))} />
      </Field>
      <div className="d-flex gap-2 mt-3">
        <ConfirmButton
          label="Save"
          icon="bi-save"
          className="btn btn-sm btn-primary"
          message={`Overwrite ${entry.key} with the edited value. The backend reads this key on the next turn.`}
          onConfirm={() => onSave({ action: "set", key: entry.key, value, ttl })}
        />
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary"
          onClick={() => onSave({ action: "expire", key: entry.key, ttl })}
        >
          <i className="bi bi-clock me-1" aria-hidden="true" />
          Set TTL only
        </button>
      </div>
    </Card>
  );
}
