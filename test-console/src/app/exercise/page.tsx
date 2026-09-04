"use client";

import { useEffect, useState } from "react";
import { Card, DataTable, Empty, ErrorNote, Field, Json, Spinner, StatusBadge } from "@/components/ui";
import { callApi, callConsole, fmtMs } from "@/lib/client";

interface Concept {
  id: string;
  name: string;
  slug: string;
}

interface GeneratedExercise {
  question_id?: string;
  text?: string;
  type?: string;
  options?: string[];
  expected_answer?: string;
  rubric?: Record<string, unknown>;
  concept_id?: string;
  difficulty?: string;
  [k: string]: unknown;
}

export default function ExercisePage() {
  const [studentId, setStudentId] = useState("");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [conceptId, setConceptId] = useState("");
  const [nQuestions, setNQuestions] = useState(3);
  const [difficulty, setDifficulty] = useState("");

  const [generated, setGenerated] = useState<GeneratedExercise[] | null>(null);
  const [genMeta, setGenMeta] = useState<{ status: number; durationMs: number } | null>(null);
  const [showAnswers, setShowAnswers] = useState(false);

  const [byConcept, setByConcept] = useState<Record<string, unknown>[] | null>(null);
  const [byConceptMeta, setByConceptMeta] = useState<{ status: number; durationMs: number } | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState<unknown>(null);

  useEffect(() => {
    void (async () => {
      const s = await callConsole<{ session: { sub: string } | null }>("/api/session");
      if (s.session?.sub) setStudentId(s.session.sub);
      const c = await callApi<Concept[]>("content/concepts", { auth: "none" });
      if (c.ok && Array.isArray(c.body)) setConcepts(c.body);
    })();
  }, []);

  const generate = async () => {
    setBusy(true);
    setError(null);
    const res = await callApi<{ exercises: GeneratedExercise[]; generated_at: string }>("exercise/generate", {
      method: "POST",
      json: {
        student_id: studentId,
        concept_id: conceptId || null,
        n_questions: nQuestions,
        difficulty: difficulty || null,
      },
    });
    setRaw(res);
    setGenMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) setGenerated(res.body.exercises ?? []);
    else setError(`POST /exercise/generate -> ${res.status}`);
    setBusy(false);
  };

  const loadByConcept = async () => {
    if (!conceptId) return;
    setBusy(true);
    setError(null);
    const res = await callApi<Record<string, unknown>[]>(`exercise/by-concept/${conceptId}`);
    setRaw(res);
    setByConceptMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) setByConcept(Array.isArray(res.body) ? res.body : []);
    else setError(`GET /exercise/by-concept -> ${res.status}`);
    setBusy(false);
  };

  return (
    <>
      <h5 className="mb-3">Exercise</h5>
      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card title="Parameters" icon="bi-sliders">
            <div className="row g-2">
              <Field label="student_id" hint="403 on mismatch" className="col-md-6">
                <input
                  className="form-control form-control-sm mono"
                  value={studentId}
                  onChange={(e) => setStudentId(e.target.value)}
                />
              </Field>
              <Field label="concept_id" className="col-md-6">
                <select
                  className="form-select form-select-sm"
                  value={conceptId}
                  onChange={(e) => setConceptId(e.target.value)}
                >
                  <option value="">(none)</option>
                  {concepts.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} — {c.slug}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="n_questions" hint="1..20" className="col-md-4">
                <input
                  type="number"
                  min={1}
                  max={20}
                  className="form-control form-control-sm"
                  value={nQuestions}
                  onChange={(e) => setNQuestions(Number(e.target.value))}
                />
              </Field>
              <Field label="difficulty" className="col-md-4">
                <select
                  className="form-select form-select-sm"
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                >
                  <option value="">(none)</option>
                  <option value="easy">easy</option>
                  <option value="medium">medium</option>
                  <option value="hard">hard</option>
                </select>
              </Field>
              <div className="col-md-4 d-flex align-items-end gap-2">
                <button type="button" className="btn btn-sm btn-primary" onClick={generate} disabled={busy || !studentId}>
                  <i className="bi bi-magic me-1" aria-hidden="true" />
                  Generate
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary"
                  onClick={loadByConcept}
                  disabled={busy || !conceptId}
                  title="GET /exercise/by-concept/{id} — audio-friendly rows only"
                >
                  <i className="bi bi-table me-1" aria-hidden="true" />
                  By concept
                </button>
                <Spinner show={busy} />
              </div>
            </div>
          </Card>

          {generated && (
            <Card
              title="POST /exercise/generate"
              icon="bi-magic"
              actions={
                <>
                  <StatusBadge status={genMeta?.status} />
                  <span className="small text-secondary">{fmtMs(genMeta?.durationMs)}</span>
                  <div className="form-check form-switch mb-0">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      id="showans"
                      checked={showAnswers}
                      onChange={(e) => setShowAnswers(e.target.checked)}
                    />
                    <label className="form-check-label small" htmlFor="showans">
                      expected_answer
                    </label>
                  </div>
                </>
              }
            >
              <div className="alert alert-warning py-1 px-2 small d-flex gap-2 align-items-start">
                <i className="bi bi-exclamation-triangle" aria-hidden="true" />
                <span>
                  This endpoint returns <code>expected_answer</code> and <code>rubric</code> to the client — the answer
                  key is exposed to any authenticated student.
                </span>
              </div>

              {generated.length === 0 ? (
                <Empty icon="bi-inbox">No exercises returned</Empty>
              ) : (
                <div className="list-group list-group-flush">
                  {generated.map((ex, i) => (
                    <div className="list-group-item" key={i}>
                      <div className="d-flex gap-2 align-items-center mb-1">
                        <span className="badge bg-secondary">#{i + 1}</span>
                        <span className="badge bg-light text-dark">{ex.type}</span>
                        <span className="badge bg-light text-dark">{ex.difficulty}</span>
                        <span className="mono small text-secondary ms-auto">{ex.question_id}</span>
                      </div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{ex.text}</div>
                      {!!ex.options?.length && (
                        <ul className="small mb-1 mt-1">
                          {ex.options.map((o, j) => (
                            <li key={j}>{o}</li>
                          ))}
                        </ul>
                      )}
                      {showAnswers && (
                        <div className="small mono text-danger-emphasis">expected_answer: {ex.expected_answer}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {byConcept && (
            <Card
              title="GET /exercise/by-concept"
              icon="bi-table"
              actions={
                <>
                  <StatusBadge status={byConceptMeta?.status} />
                  <span className="small text-secondary">{fmtMs(byConceptMeta?.durationMs)}</span>
                </>
              }
              bodyClass="card-body p-0"
            >
              <DataTable
                columns={["question", "question_type", "difficulty", "options", "id"]}
                rows={byConcept}
                emptyText="No audio-friendly exercises stored for this concept"
              />
            </Card>
          )}
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
