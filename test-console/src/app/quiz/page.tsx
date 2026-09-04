"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, DataTable, Empty, ErrorNote, Field, Json, Spinner, StatusBadge } from "@/components/ui";
import { EffectsRail } from "@/components/EffectsRail";
import { callApi, callConsole, fmtMs } from "@/lib/client";

interface Concept {
  id: string;
  name: string;
  slug: string;
  difficulty_level?: string;
}

interface QuizQuestion {
  question_id: string;
  order_index: number;
  question: string;
  question_type: string;
  options: string[];
  difficulty: string;
  audio_url: string | null;
}

interface SubmitResult {
  score: number;
  is_correct: boolean;
  feedback: string;
  next_question: QuizQuestion | null;
  quiz_complete: boolean;
  final_summary: string | null;
  cumulative_score: number;
}

interface HistoryItem {
  question: QuizQuestion;
  answer: string;
  result: SubmitResult;
  status: number;
  durationMs: number;
}

export default function QuizPage() {
  const [studentId, setStudentId] = useState("");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [conceptId, setConceptId] = useState("");
  const [nQuestions, setNQuestions] = useState(3);
  const [difficulty, setDifficulty] = useState("");
  const [language, setLanguage] = useState("id");

  const [quizSessionId, setQuizSessionId] = useState("");
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [current, setCurrent] = useState<QuizQuestion | null>(null);
  const [answer, setAnswer] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [complete, setComplete] = useState<SubmitResult | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRaw, setLastRaw] = useState<unknown>(null);
  const [askedAt, setAskedAt] = useState<number>(0);

  useEffect(() => {
    void (async () => {
      const s = await callConsole<{ session: { sub: string } | null }>("/api/session");
      if (s.session?.sub) setStudentId(s.session.sub);
      const c = await callApi<Concept[]>("content/concepts", { auth: "none" });
      if (c.ok && Array.isArray(c.body)) setConcepts(c.body);
    })();
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    setHistory([]);
    setComplete(null);
    setCurrent(null);

    const res = await callApi<Record<string, unknown>>("quiz/start", {
      method: "POST",
      json: {
        student_id: studentId,
        concept_id: conceptId || null,
        n_questions: nQuestions,
        difficulty: difficulty || null,
        language,
      },
    });
    setLastRaw(res);

    if (res.ok) {
      const body = res.body as Record<string, unknown>;
      setQuizSessionId(String(body.quiz_session_id ?? ""));
      setTotalQuestions(Number(body.total_questions ?? 0));
      setCurrent(body.first_question as QuizQuestion);
      setAskedAt(Date.now());
    } else {
      setError(`POST /quiz/start -> ${res.status}`);
    }
    setBusy(false);
  };

  const submit = async () => {
    if (!current) return;
    setBusy(true);
    setError(null);

    const latency = askedAt ? Date.now() - askedAt : null;
    const res = await callApi<SubmitResult>("quiz/submit", {
      method: "POST",
      json: {
        quiz_session_id: quizSessionId,
        question_id: current.question_id,
        student_answer: answer,
        response_latency_ms: latency,
        transcribed_from_audio: false,
      },
    });
    setLastRaw(res);

    if (res.ok) {
      const result = res.body;
      setHistory((h) => [
        ...h,
        { question: current, answer, result, status: res.status, durationMs: res.durationMs },
      ]);
      setAnswer("");
      if (result.quiz_complete) {
        setComplete(result);
        setCurrent(null);
      } else {
        setCurrent(result.next_question);
        setAskedAt(Date.now());
      }
    } else {
      setError(`POST /quiz/submit -> ${res.status}`);
    }
    setBusy(false);
  };

  const answered = history.length;

  return (
    <>
      <h5 className="mb-3">Quiz</h5>
      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card
            title="POST /quiz/start"
            icon="bi-play-circle"
            actions={
              quizSessionId ? (
                <span className="badge bg-secondary mono">
                  {answered}/{totalQuestions || "?"} answered
                </span>
              ) : null
            }
          >
            <div className="row g-2 mb-3">
              <Field label="student_id" hint="403 when it differs from the token" className="col-md-6">
                <input
                  className="form-control form-control-sm mono"
                  value={studentId}
                  onChange={(e) => setStudentId(e.target.value)}
                />
              </Field>
              <Field label="concept_id" hint="optional" className="col-md-6">
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
              <Field label="language" hint="accepted, never read" className="col-md-4">
                <select
                  className="form-select form-select-sm"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  <option value="id">id</option>
                  <option value="en">en</option>
                </select>
              </Field>
            </div>

            <button type="button" className="btn btn-sm btn-primary" onClick={start} disabled={busy || !studentId}>
              <i className="bi bi-play-fill me-1" aria-hidden="true" />
              Start quiz
              <span className="ms-2">
                <Spinner show={busy} />
              </span>
            </button>
          </Card>

          {current && (
            <Card
              title={`Question ${current.order_index + 1}`}
              icon="bi-question-circle"
              actions={
                <>
                  <span className="badge bg-secondary">{current.question_type}</span>
                  <span className="badge bg-light text-dark">{current.difficulty}</span>
                </>
              }
            >
              <p className="mb-3" style={{ whiteSpace: "pre-wrap" }}>
                {current.question}
              </p>

              {current.options?.length > 0 && (
                <div className="mb-3">
                  {current.options.map((o, i) => (
                    <div className="form-check" key={i}>
                      <input
                        className="form-check-input"
                        type="radio"
                        name="option"
                        id={`opt-${i}`}
                        checked={answer === o}
                        onChange={() => setAnswer(o)}
                      />
                      <label className="form-check-label" htmlFor={`opt-${i}`}>
                        {o}
                      </label>
                    </div>
                  ))}
                </div>
              )}

              <div className="input-group">
                <input
                  className="form-control"
                  placeholder="student_answer"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void submit();
                    }
                  }}
                />
                <button type="button" className="btn btn-primary" onClick={submit} disabled={busy || !answer.trim()}>
                  <i className="bi bi-send me-1" aria-hidden="true" />
                  Submit
                  <span className="ms-2">
                    <Spinner show={busy} />
                  </span>
                </button>
              </div>
              <div className="form-text mono">question_id: {current.question_id}</div>
            </Card>
          )}

          {complete && (
            <Card title="Quiz complete" icon="bi-flag">
              <div className="d-flex gap-2 mb-2">
                <span className="badge bg-primary">cumulative {complete.cumulative_score.toFixed(3)}</span>
              </div>
              <p style={{ whiteSpace: "pre-wrap" }}>{complete.final_summary}</p>
            </Card>
          )}

          {history.length > 0 && (
            <Card title="Attempts" icon="bi-clock-history" bodyClass="card-body p-0">
              <div className="list-group list-group-flush">
                {history.map((h, i) => (
                  <div className="list-group-item" key={i}>
                    <div className="d-flex align-items-center gap-2 mb-1">
                      <span className="badge bg-secondary">#{h.question.order_index + 1}</span>
                      <span className={`badge ${h.result.is_correct ? "bg-success" : "bg-danger"}`}>
                        {h.result.is_correct ? "correct" : "incorrect"}
                      </span>
                      <span className="badge bg-light text-dark">score {h.result.score.toFixed(2)}</span>
                      <span className="badge bg-light text-dark">cum {h.result.cumulative_score.toFixed(2)}</span>
                      <StatusBadge status={h.status} />
                      <span className="small text-secondary ms-auto">{fmtMs(h.durationMs)}</span>
                    </div>
                    <div className="small text-secondary">{h.question.question}</div>
                    <div className="small">
                      <strong>answer:</strong> {h.answer}
                    </div>
                    <div className="small text-truncate-2">{h.result.feedback}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {lastRaw != null && (
            <Card title="Last proxy response" icon="bi-code-square">
              <Json value={lastRaw} />
            </Card>
          )}
        </div>

        <EffectsRail
          sessionId={quizSessionId}
          onSessionChange={setQuizSessionId}
          extra={<QuizTables quizSessionId={quizSessionId} studentId={studentId} />}
        />
      </div>
    </>
  );
}

/* ------------------------------------------------------------ side tables */

function QuizTables({ quizSessionId, studentId }: { quizSessionId: string; studentId: string }) {
  const [rows, setRows] = useState<Record<string, Record<string, unknown>[]>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!quizSessionId && !studentId) return;
    setBusy(true);
    try {
      const jobs: [string, string][] = [];
      if (quizSessionId) {
        jobs.push(["quiz_sessions", `table=quiz_sessions&filterCol=id&filterVal=${quizSessionId}`]);
        jobs.push(["quiz_questions", `table=quiz_questions&filterCol=quiz_session_id&filterVal=${quizSessionId}&orderBy=order_index&orderDir=asc`]);
        jobs.push(["quiz_attempts", `table=quiz_attempts&filterCol=quiz_session_id&filterVal=${quizSessionId}`]);
      }
      if (studentId) {
        jobs.push(["mastery_scores", `table=mastery_scores&filterCol=student_id&filterVal=${studentId}`]);
        jobs.push(["misconceptions", `table=misconceptions&filterCol=student_id&filterVal=${studentId}`]);
      }
      const out: Record<string, Record<string, unknown>[]> = {};
      for (const [name, qs] of jobs) {
        const r = await callConsole<{ rows?: Record<string, unknown>[] }>(`/api/pg/rows?${qs}&limit=50`);
        out[name] = r.rows ?? [];
      }
      setRows(out);
    } finally {
      setBusy(false);
    }
  }, [quizSessionId, studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const specs: [string, string[]][] = [
    ["quiz_sessions", ["status", "total_questions", "correct_count", "final_score"]],
    ["quiz_questions", ["order_index", "question_type", "difficulty", "correct_answer"]],
    ["quiz_attempts", ["score", "is_correct", "student_answer", "response_latency_ms"]],
    ["mastery_scores", ["concept_id", "mastery", "confidence", "n_attempts"]],
    ["misconceptions", ["description", "resolved", "detected_at"]],
  ];

  return (
    <Card
      title="Rows touched"
      icon="bi-table"
      actions={
        <button type="button" className="btn btn-sm btn-outline-secondary" onClick={load} disabled={busy}>
          <i className="bi bi-arrow-clockwise" aria-hidden="true" />
          <span className="ms-1">
            <Spinner show={busy} />
          </span>
        </button>
      }
      bodyClass="card-body p-2"
    >
      {specs.every(([name]) => !rows[name]?.length) ? (
        <Empty icon="bi-table">Nothing yet</Empty>
      ) : (
        specs.map(([name, cols]) =>
          rows[name]?.length ? (
            <div key={name} className="mb-3">
              <div className="small fw-semibold mono mb-1">
                {name} <span className="badge bg-secondary">{rows[name].length}</span>
              </div>
              <DataTable columns={cols} rows={rows[name]} />
            </div>
          ) : null,
        )
      )}
    </Card>
  );
}
