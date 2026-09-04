"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, DataTable, Empty, ErrorNote, Json, Spinner, StatusDot } from "@/components/ui";
import { callApi, callConsole } from "@/lib/client";

interface ChunkStats {
  source: string;
  chunks: string | number;
  dim: string | number;
  min_created: string;
  max_created: string;
}

export default function VectorsPage() {
  const [backend, setBackend] = useState<string>("");
  const [configuredDim, setConfiguredDim] = useState<number | null>(null);
  const [columnDim, setColumnDim] = useState<number | null>(null);
  const [stats, setStats] = useState<ChunkStats[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [qdrant, setQdrant] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const version = await callApi<Record<string, string>>("version", { auth: "none" });
      if (version.ok) setBackend(version.body.vector_backend);

      const dimRes = await callConsole<{ rows?: { dim: string }[]; error?: string }>("/api/pg/query", {
        json: {
          sql: `select coalesce(a.atttypmod, -1) as dim
                  from pg_attribute a
                  join pg_class c on c.oid = a.attrelid
                 where c.relname = 'curriculum_chunks' and a.attname = 'embedding'`,
        },
      });
      if (dimRes.rows?.length) setColumnDim(Number(dimRes.rows[0].dim));

      const statRes = await callConsole<{ rows?: ChunkStats[]; error?: string }>("/api/pg/query", {
        json: {
          sql: `select source,
                       count(*)::int              as chunks,
                       min(vector_dims(embedding))::int as dim,
                       min(created_at)::text      as min_created,
                       max(created_at)::text      as max_created
                  from curriculum_chunks
                 group by source
                 order by count(*) desc`,
        },
      });
      if (statRes.error) setError(statRes.error);
      else setStats(statRes.rows ?? []);

      const rowRes = await callConsole<{ rows?: Record<string, unknown>[] }>(
        "/api/pg/rows?table=curriculum_chunks&limit=50&orderBy=created_at&orderDir=desc",
      );
      setRows(rowRes.rows ?? []);

      const q = await callConsole<Record<string, unknown>>("/api/qdrant");
      setQdrant(q);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void (async () => {
      const r = await callConsole<{ profile?: { embeddingDim?: number } }>("/api/health");
      if (r.profile?.embeddingDim) setConfiguredDim(Number(r.profile.embeddingDim));
    })();
  }, []);

  const mismatch =
    columnDim !== null && configuredDim !== null && columnDim > 0 && columnDim !== configuredDim;

  const qdrantInfo = qdrant?.info as Record<string, unknown> | undefined;
  const qdrantOk = Number(qdrant?.infoStatus ?? 0) === 200;

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Vectors</h5>
        <div className="d-flex align-items-center gap-2">
          {backend && <span className="badge bg-primary">VECTOR_BACKEND={backend}</span>}
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={load} disabled={busy}>
            <i className="bi bi-arrow-clockwise" aria-hidden="true" />
            <span className="ms-1">
              <Spinner show={busy} />
            </span>
          </button>
        </div>
      </div>

      <ErrorNote error={error} />

      {columnDim !== null && columnDim > 0 && (
        <div className={`alert py-2 px-3 small ${mismatch ? "alert-warning" : "alert-secondary"}`}>
          <i className={`bi ${mismatch ? "bi-exclamation-triangle" : "bi-info-circle"} me-2`} aria-hidden="true" />
          <code>curriculum_chunks.embedding</code> is <code>vector({columnDim})</code> and the active profile embeds
          at <code>{configuredDim ?? "?"}</code>.{" "}
          {mismatch
            ? "They disagree, so every insert into curriculum_chunks fails. Recreate the table at the embedding dimension from Fixtures & reset."
            : "They agree."}
        </div>
      )}

      <div className="split">
        <div>
          <Card title="curriculum_chunks by source" icon="bi-grid-3x3" bodyClass="card-body p-0">
            <DataTable
              columns={["source", "chunks", "dim", "min_created", "max_created"]}
              rows={stats as unknown as Record<string, unknown>[]}
              emptyText="No chunks stored. Run ingest_documents from Fixtures & reset."
            />
          </Card>

          <Card title="Recent chunks" icon="bi-file-earmark-text" bodyClass="card-body p-0">
            <DataTable
              columns={["content", "source", "section_title", "concept_id", "chunk_index", "embedding", "created_at"]}
              rows={rows}
              emptyText="No rows"
            />
          </Card>
        </div>

        <div>
          <Card
            title="Qdrant"
            icon="bi-diagram-2"
            actions={<StatusDot state={qdrantOk ? "ok" : "bad"} title={qdrantOk ? "reachable" : "unreachable"} />}
          >
            {!qdrant ? (
              <Empty icon="bi-diagram-2">Not checked</Empty>
            ) : !qdrantOk ? (
              <div className="small text-secondary">
                Collection <code>kodmod_curriculum</code> not reachable at{" "}
                <span className="mono">{String(qdrant.url)}</span>. Qdrant only runs behind the{" "}
                <code>qdrant</code> compose profile and is only used when <code>VECTOR_BACKEND=qdrant</code>.
              </div>
            ) : (
              <>
                <div className="d-flex gap-2 mb-2">
                  <span className="badge bg-secondary mono">{String(qdrant.collection)}</span>
                </div>
                <Json value={qdrantInfo} />
              </>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
