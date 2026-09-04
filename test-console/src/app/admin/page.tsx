"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, ConfirmButton, Empty, ErrorNote, Field, Json, Spinner, StatusDot } from "@/components/ui";
import { callConsole, fmtMs } from "@/lib/client";

interface ScriptInfo {
  name: string;
  label: string;
  destructive: boolean;
  command: string;
}

interface FixtureInfo {
  fixtures: {
    students: { id: string; full_name: string }[];
    teachers: { id: string; full_name: string }[];
    classrooms: { id: string; name: string }[];
  };
  presets: string[];
  present: { students: number; teachers: number; classrooms: number };
  concepts: { id: string; slug: string; name: string }[];
}

export default function AdminPage() {
  const [scripts, setScripts] = useState<ScriptInfo[]>([]);
  const [runnerMeta, setRunnerMeta] = useState<{ cwd: string; python: string } | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [output, setOutput] = useState<{ script: string; exitCode: number; durationMs: number; output: string } | null>(null);
  const [info, setInfo] = useState<FixtureInfo | null>(null);
  const [students, setStudents] = useState<{ id: string; full_name: string }[]>([]);
  const [masteryStudent, setMasteryStudent] = useState("");
  const [preset, setPreset] = useState("mixed");
  const [dim, setDim] = useState(1024);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, f, ids, health] = await Promise.all([
        callConsole<{ scripts: ScriptInfo[]; cwd: string; python: string }>("/api/admin/run"),
        callConsole<FixtureInfo>("/api/admin/fixtures"),
        callConsole<{ students: { id: string; full_name: string }[] }>("/api/identities"),
        callConsole<{ profile?: { embeddingDim?: number } }>("/api/health"),
      ]);
      setScripts(s.scripts ?? []);
      setRunnerMeta({ cwd: s.cwd, python: s.python });
      setInfo(f);
      setStudents(ids.students ?? []);
      if (!masteryStudent && ids.students?.length) setMasteryStudent(ids.students[0].id);
      if (health.profile?.embeddingDim) setDim(Number(health.profile.embeddingDim));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [masteryStudent]);

  useEffect(() => {
    void load();
  }, [load]);

  const runScript = async (name: string) => {
    setRunning(name);
    setOutput(null);
    setError(null);
    try {
      const res = await callConsole<{ ok: boolean; exitCode: number; durationMs: number; output: string; error?: string }>(
        "/api/admin/run",
        { json: { script: name } },
      );
      if (res.error) setError(res.error);
      else setOutput({ script: name, exitCode: res.exitCode, durationMs: res.durationMs, output: res.output });
      await load();
    } finally {
      setRunning(null);
    }
  };

  const fixture = async (payload: Record<string, unknown>, successNote: string) => {
    setBusy(true);
    setError(null);
    setNote(null);
    const res = await callConsole<{ ok?: boolean; error?: string } & Record<string, unknown>>("/api/admin/fixtures", {
      json: payload,
    });
    if (res.error) setError(res.error);
    else setNote(`${successNote} ${JSON.stringify(res)}`);
    await load();
    setBusy(false);
  };

  const fixturesPresent =
    info && info.present.students === 3 && info.present.teachers === 1 && info.present.classrooms === 1;

  return (
    <>
      <h5 className="mb-3">Fixtures &amp; reset</h5>
      <div className="alert alert-warning py-1 px-2 small d-flex gap-2 align-items-center">
        <i className="bi bi-exclamation-triangle" aria-hidden="true" />
        <span>Everything on this page writes to the datastores of the active profile.</span>
      </div>

      <ErrorNote error={error} />
      {note && (
        <div className="alert alert-success py-1 px-2 small mono d-flex justify-content-between align-items-center">
          <span>{note}</span>
          <button type="button" className="btn-close" aria-label="Dismiss" onClick={() => setNote(null)} />
        </div>
      )}

      <div className="split">
        <div>
          <Card
            title="Python scripts"
            icon="bi-terminal"
            actions={
              runnerMeta ? (
                <span className="small mono text-secondary text-truncate" style={{ maxWidth: 320 }} title={runnerMeta.cwd}>
                  {runnerMeta.python} · {runnerMeta.cwd}
                </span>
              ) : null
            }
            bodyClass="card-body p-0"
          >
            <div className="list-group list-group-flush">
              {scripts.map((s) => (
                <div className="list-group-item d-flex align-items-center gap-3" key={s.name}>
                  <div className="flex-grow-1">
                    <div className="d-flex align-items-center gap-2">
                      <span className="fw-semibold mono">{s.name}</span>
                      {s.destructive && <span className="badge bg-danger">destructive</span>}
                    </div>
                    <div className="small text-secondary">{s.label}</div>
                    <div className="small mono text-secondary">{s.command}</div>
                  </div>
                  {s.destructive ? (
                    <ConfirmButton
                      label="Run"
                      icon="bi-play-fill"
                      className="btn btn-sm btn-outline-danger"
                      disabled={!!running}
                      message={`Run ${s.command} against the active profile's database. This recreates schema objects and can drop existing data.`}
                      onConfirm={() => runScript(s.name)}
                    />
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-primary"
                      disabled={!!running}
                      onClick={() => runScript(s.name)}
                    >
                      <i className="bi bi-play-fill me-1" aria-hidden="true" />
                      Run
                    </button>
                  )}
                  {running === s.name && <Spinner show />}
                </div>
              ))}
              {scripts.length === 0 && <Empty icon="bi-terminal">No scripts available</Empty>}
            </div>
          </Card>

          {output && (
            <Card
              title={`${output.script} output`}
              icon="bi-file-earmark-text"
              actions={
                <>
                  <span className={`badge ${output.exitCode === 0 ? "bg-success" : "bg-danger"}`}>
                    exit {output.exitCode}
                  </span>
                  <span className="small text-secondary">{fmtMs(output.durationMs)}</span>
                </>
              }
            >
              <pre className="out">{output.output || "(no output)"}</pre>
            </Card>
          )}

          <Card
            title="Test fixtures"
            icon="bi-people"
            actions={
              info ? (
                <span className="d-flex align-items-center gap-2 small">
                  <StatusDot state={fixturesPresent ? "ok" : "warn"} />
                  {info.present.students}/3 students · {info.present.teachers}/1 teacher ·{" "}
                  {info.present.classrooms}/1 classroom
                </span>
              ) : null
            }
          >
            <div className="small text-secondary mb-2">
              The fixed UUIDs in <code>tests/conftest.py:57-61</code> are referenced by the test plan but created by no
              seed script. This also enrolls all three students in the classroom, which is what the classroom analytics
              journey needs.
            </div>

            {info && (
              <table className="table table-sm mono small">
                <tbody>
                  {info.fixtures.students.map((s) => (
                    <tr key={s.id}>
                      <td className="text-secondary">student</td>
                      <td>{s.full_name}</td>
                      <td className="text-break">{s.id}</td>
                    </tr>
                  ))}
                  {info.fixtures.teachers.map((t) => (
                    <tr key={t.id}>
                      <td className="text-secondary">teacher</td>
                      <td>{t.full_name}</td>
                      <td className="text-break">{t.id}</td>
                    </tr>
                  ))}
                  {info.fixtures.classrooms.map((c) => (
                    <tr key={c.id}>
                      <td className="text-secondary">classroom</td>
                      <td>{c.name}</td>
                      <td className="text-break">{c.id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={busy}
              onClick={() => fixture({ action: "createFixtures" }, "fixtures created")}
            >
              <i className="bi bi-person-plus me-1" aria-hidden="true" />
              Create or update fixtures
              <span className="ms-2">
                <Spinner show={busy} />
              </span>
            </button>
          </Card>

          <Card title="Mastery preset" icon="bi-graph-up">
            <div className="row g-2 align-items-end">
              <Field label="student" className="col-md-6">
                <select
                  className="form-select form-select-sm"
                  value={masteryStudent}
                  onChange={(e) => setMasteryStudent(e.target.value)}
                >
                  {students.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.full_name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="preset" hint="docs/testplan/test-data.md" className="col-md-3">
                <select className="form-select form-select-sm" value={preset} onChange={(e) => setPreset(e.target.value)}>
                  {(info?.presets ?? []).map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="col-md-3">
                <button
                  type="button"
                  className="btn btn-sm btn-primary w-100"
                  disabled={busy || !masteryStudent}
                  onClick={() => fixture({ action: "applyMastery", studentId: masteryStudent, preset }, "mastery applied")}
                >
                  <i className="bi bi-check2 me-1" aria-hidden="true" />
                  Apply
                </button>
              </div>
            </div>
            {info && info.concepts.length === 0 && (
              <div className="alert alert-warning py-1 px-2 small mt-2 mb-0">
                No concepts seeded, so the preset would write nothing. Run <code>seed_curriculum</code> first.
              </div>
            )}
          </Card>
        </div>

        <div>
          <Card title="Reset" icon="bi-trash3">
            <div className="d-grid gap-2">
              <ConfirmButton
                label="Truncate learning activity"
                icon="bi-eraser"
                message="Truncate quiz_attempts, quiz_questions, quiz_sessions, interaction_logs, learning_sessions, mastery_scores, misconceptions, analytics_reports and recommendations. Students, curriculum and vectors are kept."
                onConfirm={() => fixture({ action: "truncate", scope: "activity" }, "activity truncated")}
              />
              <ConfirmButton
                label="Truncate curriculum"
                icon="bi-eraser"
                message="Truncate exercises, lessons, concepts, subjects and curriculum_chunks. Re-run seed_curriculum and ingest_documents afterwards."
                onConfirm={() => fixture({ action: "truncate", scope: "curriculum" }, "curriculum truncated")}
              />
              <ConfirmButton
                label="Truncate everything"
                icon="bi-exclamation-octagon"
                message="Truncate every application table: activity, curriculum, students, teachers, classrooms and enrollment. Checkpoints are not touched."
                onConfirm={() => fixture({ action: "truncate", scope: "all" }, "all tables truncated")}
              />
              <ConfirmButton
                label="Wipe Redis kodmod:*"
                icon="bi-hdd"
                message="Delete every kodmod:* key. In-progress quizzes and tutoring windows are lost."
                onConfirm={() => fixture({ action: "wipeRedis", pattern: "kodmod:*" }, "redis wiped")}
              />
              <ConfirmButton
                label="Purge all checkpoints"
                icon="bi-diagram-3"
                message="Delete every row from checkpoints, checkpoint_blobs and checkpoint_writes. All graph traces and resumable conversation state are lost."
                onConfirm={() => fixture({ action: "purgeCheckpoints" }, "checkpoints purged")}
              />
            </div>
          </Card>

          <Card title="Recreate curriculum_chunks" icon="bi-grid-3x3">
            <div className="small text-secondary mb-2">
              Drops and recreates the table with the HNSW cosine index, at the embedding dimension you pick. Use this
              when the vector column width and <code>EMBEDDING_DIM</code> disagree.
            </div>
            <Field label="vector dimension">
              <input
                type="number"
                className="form-control form-control-sm"
                value={dim}
                onChange={(e) => setDim(Number(e.target.value))}
              />
            </Field>
            <div className="mt-2">
              <ConfirmButton
                label={`Recreate at vector(${dim})`}
                icon="bi-arrow-repeat"
                message={`Drop curriculum_chunks and recreate it as vector(${dim}). Every stored chunk is deleted; re-run ingest_documents afterwards.`}
                onConfirm={() => fixture({ action: "resetChunks", dim }, "curriculum_chunks recreated")}
              />
            </div>
          </Card>

          {info && (
            <Card title="Seeded concepts" icon="bi-book" bodyClass="card-body p-2">
              {info.concepts.length === 0 ? (
                <Empty icon="bi-book">None</Empty>
              ) : (
                <Json value={info.concepts.map((c) => ({ slug: c.slug, name: c.name, id: c.id }))} />
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
