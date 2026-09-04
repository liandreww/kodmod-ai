"use client";

import { useEffect, useState } from "react";
import { Card, DataTable, Empty, ErrorNote, Field, Json, Spinner, StatusBadge } from "@/components/ui";
import { callApi, callConsole, fmtMs } from "@/lib/client";

type Window = "today" | "week" | "month" | "all";

interface Rollup {
  error?: string;
  student_id?: string;
  student_name?: string;
  window?: string;
  n_sessions?: number;
  total_minutes?: number;
  interaction_count?: number;
  n_quiz_attempts?: number;
  quiz_accuracy?: number;
  avg_quiz_score?: number;
  overall_mastery?: number;
  engagement_index?: number;
  weak_concepts?: Record<string, unknown>[];
  strong_concepts?: Record<string, unknown>[];
  open_misconceptions?: Record<string, unknown>[];
  active_recommendations?: unknown[];
  generated_at?: string;
  [k: string]: unknown;
}

interface ClassroomRollup extends Rollup {
  classroom_id?: string;
  classroom_name?: string;
  n_students?: number;
  avg_mastery?: number;
  avg_quiz_accuracy?: number;
  avg_engagement_index?: number;
  class_weak_concepts?: Record<string, unknown>[];
  students?: Record<string, unknown>[];
}

export default function AnalyticsPage() {
  const [role, setRole] = useState<string>("student");
  const [studentId, setStudentId] = useState("");
  const [classroomId, setClassroomId] = useState("");
  const [classrooms, setClassrooms] = useState<{ id: string; name: string; enrolled: number }[]>([]);
  const [window, setWindow] = useState<Window>("month");

  const [rollup, setRollup] = useState<Rollup | null>(null);
  const [spoken, setSpoken] = useState<string | null>(null);
  const [classroom, setClassroom] = useState<ClassroomRollup | null>(null);
  const [alerts, setAlerts] = useState<Record<string, unknown> | null>(null);

  const [meta, setMeta] = useState<{ status: number; durationMs: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState<unknown>(null);

  useEffect(() => {
    void (async () => {
      const s = await callConsole<{ session: { sub: string; role: string } | null }>("/api/session");
      if (s.session) {
        setRole(s.session.role);
        if (s.session.role === "student") setStudentId(s.session.sub);
      }
      const c = await callConsole<{ classrooms: { id: string; name: string; enrolled: number }[] }>("/api/identities");
      setClassrooms(c.classrooms ?? []);
      if (c.classrooms?.length) setClassroomId(c.classrooms[0].id);
    })();
  }, []);

  const loadStudent = async () => {
    setBusy(true);
    setError(null);
    setSpoken(null);
    const res = await callApi<Rollup>(`analytics/student/${studentId}`, { search: { window } });
    setRaw(res);
    setMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) {
      setRollup(res.body);
      if (res.body?.error) setError(`HTTP 200 with in-band error: ${res.body.error}`);
    } else {
      setRollup(null);
      setError(`GET /analytics/student/{id} -> ${res.status}`);
    }
    setBusy(false);
  };

  const loadSpoken = async () => {
    setBusy(true);
    const res = await callApi<{ spoken: string; rollup: Rollup }>(`analytics/student/${studentId}/spoken`, {
      search: { window },
    });
    setRaw(res);
    setMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) {
      setSpoken(res.body.spoken);
      setRollup(res.body.rollup);
    } else setError(`GET /analytics/student/{id}/spoken -> ${res.status}`);
    setBusy(false);
  };

  const loadClassroom = async () => {
    setBusy(true);
    setError(null);
    const res = await callApi<ClassroomRollup>(`analytics/classroom/${classroomId}`, { search: { window } });
    setRaw(res);
    setMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) {
      setClassroom(res.body);
      if (res.body?.error) setError(`HTTP 200 with in-band error: ${res.body.error}`);
      else if (res.body?.students === undefined) {
        setError("Empty roster: the response omits avg_*, students and class_weak_concepts.");
      }
    } else {
      setClassroom(null);
      setError(`GET /analytics/classroom/{id} -> ${res.status}${res.status === 403 ? " (needs a teacher token)" : ""}`);
    }
    setBusy(false);
  };

  const loadAlerts = async () => {
    setBusy(true);
    const res = await callApi<Record<string, unknown>>(`analytics/classroom/${classroomId}/alerts`, {
      search: { window },
    });
    setRaw(res);
    setMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) setAlerts(res.body);
    else setError(`GET /analytics/classroom/{id}/alerts -> ${res.status}`);
    setBusy(false);
  };

  const metrics: [string, unknown][] = rollup
    ? [
        ["overall_mastery", rollup.overall_mastery],
        ["quiz_accuracy", rollup.quiz_accuracy],
        ["avg_quiz_score", rollup.avg_quiz_score],
        ["engagement_index", rollup.engagement_index],
        ["n_sessions", rollup.n_sessions],
        ["n_quiz_attempts", rollup.n_quiz_attempts],
        ["interaction_count", rollup.interaction_count],
        ["total_minutes", rollup.total_minutes],
      ]
    : [];

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Analytics</h5>
        <div className="d-flex align-items-center gap-2">
          <span className="small text-secondary">window</span>
          <div className="btn-group btn-group-sm">
            {(["today", "week", "month", "all"] as Window[]).map((w) => (
              <button
                key={w}
                type="button"
                className={`btn ${window === w ? "btn-primary" : "btn-outline-secondary"}`}
                onClick={() => setWindow(w)}
              >
                {w}
              </button>
            ))}
          </div>
        </div>
      </div>

      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card
            title="Student rollup"
            icon="bi-person-lines-fill"
            actions={
              <>
                <StatusBadge status={meta?.status} />
                <span className="small text-secondary">{fmtMs(meta?.durationMs)}</span>
              </>
            }
          >
            <div className="row g-2 align-items-end mb-3">
              <Field label="student_id" hint="403 for another student" className="col-md-8">
                <input
                  className="form-control form-control-sm mono"
                  value={studentId}
                  onChange={(e) => setStudentId(e.target.value)}
                />
              </Field>
              <div className="col-md-4 d-flex gap-2">
                <button type="button" className="btn btn-sm btn-primary" onClick={loadStudent} disabled={busy || !studentId}>
                  <i className="bi bi-bar-chart me-1" aria-hidden="true" />
                  Rollup
                </button>
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={loadSpoken} disabled={busy || !studentId}>
                  <i className="bi bi-volume-up me-1" aria-hidden="true" />
                  Spoken
                </button>
                <Spinner show={busy} />
              </div>
            </div>

            {spoken && (
              <div className="alert alert-info py-2 px-3 small mb-3" role="status">
                {spoken}
              </div>
            )}

            {!rollup ? (
              <Empty icon="bi-bar-chart">No rollup loaded</Empty>
            ) : rollup.error ? (
              <div className="alert alert-warning py-2 px-3 small mb-0 mono">error: {rollup.error}</div>
            ) : (
              <>
                <div className="row row-cols-2 row-cols-md-4 g-2 mb-3">
                  {metrics.map(([k, v]) => (
                    <div className="col" key={k}>
                      <div className="border rounded p-2 h-100">
                        <div className="fs-5 fw-semibold">
                          {typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) : String(v ?? "-")}
                        </div>
                        <div className="small text-secondary mono">{k}</div>
                      </div>
                    </div>
                  ))}
                </div>

                {!!rollup.weak_concepts?.length && (
                  <>
                    <div className="small fw-semibold mb-1">weak_concepts</div>
                    <DataTable
                      columns={["concept_name", "mastery", "n_attempts", "concept_id"]}
                      rows={rollup.weak_concepts}
                    />
                  </>
                )}
                {!!rollup.strong_concepts?.length && (
                  <>
                    <div className="small fw-semibold mb-1 mt-3">strong_concepts</div>
                    <DataTable
                      columns={["concept_name", "mastery", "n_attempts", "concept_id"]}
                      rows={rollup.strong_concepts}
                    />
                  </>
                )}
                {!!rollup.open_misconceptions?.length && (
                  <>
                    <div className="small fw-semibold mb-1 mt-3">open_misconceptions</div>
                    <DataTable
                      columns={["concept_name", "description", "detected_at"]}
                      rows={rollup.open_misconceptions}
                    />
                  </>
                )}
              </>
            )}
          </Card>

          <Card
            title="Classroom"
            icon="bi-people"
            actions={
              role !== "teacher" ? <span className="badge bg-warning text-dark">needs a teacher token</span> : null
            }
          >
            <div className="row g-2 align-items-end mb-3">
              <Field label="classroom_id" className="col-md-8">
                <select
                  className="form-select form-select-sm"
                  value={classroomId}
                  onChange={(e) => setClassroomId(e.target.value)}
                >
                  <option value="">(pick one)</option>
                  {classrooms.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} — {c.enrolled} enrolled
                    </option>
                  ))}
                </select>
              </Field>
              <div className="col-md-4 d-flex gap-2">
                <button type="button" className="btn btn-sm btn-primary" onClick={loadClassroom} disabled={busy || !classroomId}>
                  <i className="bi bi-bar-chart me-1" aria-hidden="true" />
                  Rollup
                </button>
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={loadAlerts} disabled={busy || !classroomId}>
                  <i className="bi bi-bell me-1" aria-hidden="true" />
                  Alerts
                </button>
              </div>
            </div>

            {classroom && !classroom.error && (
              <>
                <div className="d-flex gap-2 flex-wrap mb-3">
                  <span className="badge bg-secondary">{classroom.classroom_name}</span>
                  <span className="badge bg-light text-dark">n_students {classroom.n_students}</span>
                  {classroom.avg_mastery !== undefined && (
                    <span className="badge bg-light text-dark">avg_mastery {classroom.avg_mastery?.toFixed(3)}</span>
                  )}
                  {classroom.avg_quiz_accuracy !== undefined && (
                    <span className="badge bg-light text-dark">
                      avg_quiz_accuracy {classroom.avg_quiz_accuracy?.toFixed(3)}
                    </span>
                  )}
                </div>
                {classroom.students ? (
                  <DataTable
                    columns={["student_name", "overall_mastery", "quiz_accuracy", "engagement_index", "student_id"]}
                    rows={classroom.students}
                  />
                ) : (
                  <Empty icon="bi-people">
                    Empty roster — the aggregator returns a reduced shape with no student list.
                  </Empty>
                )}
              </>
            )}

            {alerts && (
              <div className="mt-3">
                <div className="small fw-semibold mb-1">alerts</div>
                {Array.isArray(alerts.alerts) && alerts.alerts.length ? (
                  (alerts.alerts as { level: string; title: string; detail: string }[]).map((a, i) => (
                    <div
                      key={i}
                      className={`alert py-1 px-2 small mb-1 ${a.level === "warning" ? "alert-warning" : "alert-info"}`}
                    >
                      <strong>{a.title}</strong> — {a.detail}
                    </div>
                  ))
                ) : (
                  <Empty icon="bi-bell-slash">No alerts</Empty>
                )}
              </div>
            )}
          </Card>
        </div>

        <div>
          <Card title="Raw response" icon="bi-code-square">
            {raw == null ? <Empty icon="bi-code">Nothing yet</Empty> : <Json value={raw} tall />}
          </Card>
        </div>
      </div>
    </>
  );
}
