"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, DataTable, Empty, ErrorNote, Field, Json, Spinner, StatusBadge } from "@/components/ui";
import { callApi, callConsole, fmtMs } from "@/lib/client";

interface Concept {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  difficulty_level: string;
}

interface Lesson {
  id: string;
  concept_id: string;
  title: string;
  body_md: string;
  audio_friendly_summary: string | null;
  estimated_minutes: number;
}

interface Chunk {
  id?: string;
  text?: string;
  source?: string;
  section_title?: string;
  score?: number;
  rerank_score?: number;
  accessibility_metadata?: unknown;
  [k: string]: unknown;
}

export default function ContentPage() {
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [subjects, setSubjects] = useState<{ id: string; name: string }[]>([]);
  const [subjectId, setSubjectId] = useState("");
  const [selected, setSelected] = useState<Concept | null>(null);
  const [lessons, setLessons] = useState<Lesson[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("cara menjumlahkan pecahan berbeda penyebut");
  const [topK, setTopK] = useState(5);
  const [language, setLanguage] = useState("id");
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  const [retrieveMeta, setRetrieveMeta] = useState<{ status: number; durationMs: number } | null>(null);
  const [raw, setRaw] = useState<unknown>(null);

  const loadConcepts = useCallback(async () => {
    setBusy(true);
    setError(null);
    const res = await callApi<Concept[]>("content/concepts", {
      auth: "none",
      search: { subject_id: subjectId || undefined },
    });
    if (res.ok && Array.isArray(res.body)) setConcepts(res.body);
    else setError(`GET /content/concepts -> ${res.status}`);
    setBusy(false);
  }, [subjectId]);

  useEffect(() => {
    void loadConcepts();
  }, [loadConcepts]);

  useEffect(() => {
    void (async () => {
      const r = await callConsole<{ rows?: { id: string; name: string }[] }>(
        "/api/pg/rows?table=subjects&limit=100&orderBy=name&orderDir=asc",
      );
      setSubjects(r.rows ?? []);
    })();
  }, []);

  const openConcept = async (c: Concept) => {
    setSelected(c);
    setLessons(null);
    const res = await callApi<Lesson[]>(`content/concepts/${c.id}/lessons`, { auth: "none" });
    if (res.ok) setLessons(Array.isArray(res.body) ? res.body : []);
  };

  const retrieve = async () => {
    setBusy(true);
    setError(null);
    const res = await callApi<{ chunks: Chunk[]; query: string }>("content/retrieve", {
      method: "POST",
      auth: "none",
      json: { query, top_k: topK, language },
    });
    setRaw(res);
    setRetrieveMeta({ status: res.status, durationMs: res.durationMs });
    if (res.ok) setChunks(res.body.chunks ?? []);
    else setError(`POST /content/retrieve -> ${res.status} (422 means top_k is outside 1..20)`);
    setBusy(false);
  };

  return (
    <>
      <h5 className="mb-3">Content &amp; RAG</h5>
      <div className="alert alert-secondary py-1 px-2 small">
        All four <code>/content/*</code> routes are unauthenticated by design
        (<span className="mono">tests/api/test_authz_inventory.py:26-29</span>), so these calls are sent without a token.
      </div>
      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card
            title="Concepts"
            icon="bi-book"
            actions={
              <>
                <select
                  className="form-select form-select-sm"
                  style={{ width: 200 }}
                  value={subjectId}
                  onChange={(e) => setSubjectId(e.target.value)}
                >
                  <option value="">All subjects</option>
                  {subjects.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={loadConcepts}>
                  <i className="bi bi-arrow-clockwise" aria-hidden="true" />
                </button>
              </>
            }
            bodyClass="card-body p-0"
          >
            <DataTable
              columns={["name", "slug", "difficulty_level", "id"]}
              rows={concepts as unknown as Record<string, unknown>[]}
              onRowClick={(row) => openConcept(row as unknown as Concept)}
              activeIndex={selected ? concepts.findIndex((c) => c.id === selected.id) : undefined}
              emptyText="No concepts. Run seed_curriculum from Fixtures & reset."
            />
          </Card>

          {selected && (
            <Card title={selected.name} icon="bi-journal-text">
              <p className="small text-secondary">{selected.description}</p>
              <div className="mono small text-secondary mb-3">
                {selected.slug} · {selected.difficulty_level} · {selected.id}
              </div>

              <div className="fw-semibold small mb-2">Lessons</div>
              {lessons === null ? (
                <Spinner show />
              ) : lessons.length === 0 ? (
                <Empty icon="bi-journal-x">
                  No lessons. Only pecahan, fotosintesis and tata-surya are seeded with lessons.
                </Empty>
              ) : (
                lessons.map((l) => (
                  <div className="border rounded p-2 mb-2" key={l.id}>
                    <div className="d-flex gap-2 align-items-center mb-1">
                      <span className="fw-semibold">{l.title}</span>
                      <span className="badge bg-light text-dark ms-auto">{l.estimated_minutes} min</span>
                    </div>
                    {l.audio_friendly_summary && (
                      <div className="small text-secondary mb-2">{l.audio_friendly_summary}</div>
                    )}
                    <details>
                      <summary className="small text-secondary">body_md</summary>
                      <pre className="out">{l.body_md}</pre>
                    </details>
                  </div>
                ))
              )}
            </Card>
          )}
        </div>

        <div>
          <Card
            title="POST /content/retrieve"
            icon="bi-search"
            actions={
              <>
                <StatusBadge status={retrieveMeta?.status} />
                <span className="small text-secondary">{fmtMs(retrieveMeta?.durationMs)}</span>
              </>
            }
          >
            <Field label="query">
              <textarea
                className="form-control form-control-sm"
                rows={2}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </Field>
            <div className="row g-2 mt-1">
              <Field label="top_k" hint="1..20" className="col-6">
                <input
                  type="number"
                  className="form-control form-control-sm"
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                />
              </Field>
              <Field label="language" className="col-6">
                <input
                  className="form-control form-control-sm"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                />
              </Field>
            </div>
            <button type="button" className="btn btn-sm btn-primary mt-3 w-100" onClick={retrieve} disabled={busy}>
              <i className="bi bi-search me-1" aria-hidden="true" />
              Retrieve
              <span className="ms-2">
                <Spinner show={busy} />
              </span>
            </button>
          </Card>

          {chunks && (
            <Card title={`Chunks (${chunks.length})`} icon="bi-file-earmark-text">
              {chunks.length === 0 ? (
                <Empty icon="bi-file-earmark-x">
                  Nothing retrieved. curriculum_chunks may be empty — run ingest_documents.
                </Empty>
              ) : (
                chunks.map((c, i) => (
                  <div className="border rounded p-2 mb-2" key={i}>
                    <div className="d-flex gap-2 align-items-center mb-1 small">
                      <span className="badge bg-primary">
                        score {typeof c.score === "number" ? c.score.toFixed(4) : "-"}
                      </span>
                      {typeof c.rerank_score === "number" && (
                        <span className="badge bg-info text-dark">rerank {c.rerank_score.toFixed(4)}</span>
                      )}
                      <span className="text-secondary ms-auto mono">{c.source}</span>
                    </div>
                    {c.section_title && <div className="small fw-semibold">{c.section_title}</div>}
                    <div className="small" style={{ whiteSpace: "pre-wrap" }}>
                      {c.text}
                    </div>
                  </div>
                ))
              )}
            </Card>
          )}

          {raw != null && (
            <Card title="Raw response" icon="bi-code-square">
              <Json value={raw} />
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
