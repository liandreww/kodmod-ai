"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, ConfirmButton, DataTable, Empty, ErrorNote, Field, Json, Spinner, cellText } from "@/components/ui";
import { callConsole, fmtMs } from "@/lib/client";

interface ColumnMeta {
  column_name: string;
  data_type: string;
  udt_name: string;
  is_nullable: string;
  column_default: string | null;
}

interface TableMeta {
  name: string;
  columns: ColumnMeta[];
  primaryKey: string[];
  unique: { name: string; columns: string[] }[];
  foreignKeys: { column: string; refTable: string; refColumn: string }[];
  indexes: { name: string; def: string }[];
}

interface RowsResponse {
  table: string;
  columns: ColumnMeta[];
  primaryKey: string[];
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
  sql: string;
  durationMs: number;
  error?: string;
}

export default function DbPage() {
  const [schema, setSchema] = useState<TableMeta[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [table, setTable] = useState("");
  const [data, setData] = useState<RowsResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(50);
  const [orderBy, setOrderBy] = useState("");
  const [orderDir, setOrderDir] = useState<"asc" | "desc">("desc");
  const [filterCol, setFilterCol] = useState("");
  const [filterVal, setFilterVal] = useState("");
  const [selectedRow, setSelectedRow] = useState<Record<string, unknown> | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [insertMode, setInsertMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"rows" | "schema" | "sql">("rows");

  const meta = useMemo(() => schema.find((t) => t.name === table), [schema, table]);

  const loadSchema = useCallback(async () => {
    const [s, c] = await Promise.all([
      callConsole<{ tables: TableMeta[] }>("/api/pg/schema"),
      callConsole<{ counts: Record<string, number> }>("/api/pg/counts").catch(() => ({ counts: {} })),
    ]);
    setSchema(s.tables ?? []);
    setCounts(c.counts ?? {});
  }, []);

  const loadRows = useCallback(async () => {
    if (!table) return;
    setBusy(true);
    setError(null);
    const qs = new URLSearchParams({
      table,
      limit: String(limit),
      offset: String(offset),
      orderDir,
    });
    if (orderBy) qs.set("orderBy", orderBy);
    if (filterCol && filterVal) {
      qs.set("filterCol", filterCol);
      qs.set("filterVal", filterVal);
    }
    const res = await callConsole<RowsResponse>(`/api/pg/rows?${qs}`);
    if (res.error) setError(res.error);
    else setData(res);
    setBusy(false);
  }, [table, limit, offset, orderBy, orderDir, filterCol, filterVal]);

  useEffect(() => {
    void loadSchema();
    const fromUrl = new URLSearchParams(window.location.search).get("table");
    if (fromUrl) setTable(fromUrl);
  }, [loadSchema]);

  useEffect(() => {
    void loadRows();
  }, [loadRows]);

  useEffect(() => {
    setOffset(0);
    setSelectedRow(null);
    setInsertMode(false);
    setFilterCol("");
    setFilterVal("");
    setOrderBy("");
  }, [table]);

  const pkWhere = (row: Record<string, unknown>): Record<string, unknown> => {
    const pk = data?.primaryKey ?? [];
    if (!pk.length) return row;
    return Object.fromEntries(pk.map((k) => [k, row[k]]));
  };

  const mutate = async (payload: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    const res = await callConsole<{ ok?: boolean; error?: string }>("/api/pg/rows", { json: payload });
    if (res.error) setError(res.error);
    else {
      setSelectedRow(null);
      setInsertMode(false);
      await loadRows();
      await loadSchema();
    }
    setBusy(false);
  };

  const appTables = schema.filter((t) => !t.name.startsWith("checkpoint"));
  const cpTables = schema.filter((t) => t.name.startsWith("checkpoint"));

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Postgres</h5>
        <button type="button" className="btn btn-sm btn-outline-secondary" onClick={loadSchema}>
          <i className="bi bi-arrow-clockwise me-1" aria-hidden="true" />
          Reload schema
        </button>
      </div>

      <div className="alert alert-secondary py-1 px-2 small">
        Introspected from <code>information_schema</code>. <code>database/schema.sql</code> in the Python repo is stale
        and diverges from <code>database/models.py</code>; the live DDL is <code>scripts/create_test_db.py</code>.
      </div>

      <ErrorNote error={error} />

      <div className="row g-3">
        <div className="col-lg-3">
          <Card title="Tables" icon="bi-list-ul" bodyClass="card-body p-0">
            <div className="list-group list-group-flush" style={{ maxHeight: "70vh", overflowY: "auto" }}>
              {appTables.map((t) => (
                <button
                  key={t.name}
                  type="button"
                  className={`list-group-item list-group-item-action py-1 d-flex justify-content-between align-items-center ${
                    table === t.name ? "active" : ""
                  }`}
                  onClick={() => setTable(t.name)}
                >
                  <span className="mono small">{t.name}</span>
                  <span className={`badge ${table === t.name ? "bg-light text-dark" : "bg-secondary"}`}>
                    {counts[t.name] ?? "-"}
                  </span>
                </button>
              ))}
              {cpTables.length > 0 && (
                <div className="list-group-item bg-body-secondary small text-uppercase text-secondary py-1">
                  LangGraph
                </div>
              )}
              {cpTables.map((t) => (
                <button
                  key={t.name}
                  type="button"
                  className={`list-group-item list-group-item-action py-1 d-flex justify-content-between align-items-center ${
                    table === t.name ? "active" : ""
                  }`}
                  onClick={() => setTable(t.name)}
                >
                  <span className="mono small">{t.name}</span>
                  <span className={`badge ${table === t.name ? "bg-light text-dark" : "bg-secondary"}`}>
                    {counts[t.name] ?? "-"}
                  </span>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <div className="col-lg-9">
          <ul className="nav nav-tabs mb-3">
            {(
              [
                ["rows", "Rows", "bi-table"],
                ["schema", "Schema", "bi-diagram-2"],
                ["sql", "SQL", "bi-terminal"],
              ] as ["rows" | "schema" | "sql", string, string][]
            ).map(([id, label, icon]) => (
              <li className="nav-item" key={id}>
                <button type="button" className={`nav-link ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>
                  <i className={`bi ${icon} me-1`} aria-hidden="true" />
                  {label}
                </button>
              </li>
            ))}
          </ul>

          {tab === "sql" && <SqlRunner />}

          {tab === "schema" &&
            (!meta ? (
              <Empty icon="bi-diagram-2">Pick a table</Empty>
            ) : (
              <>
                <Card title={`${meta.name} columns`} icon="bi-columns" bodyClass="card-body p-0">
                  <DataTable
                    columns={["column_name", "data_type", "udt_name", "is_nullable", "column_default"]}
                    rows={meta.columns as unknown as Record<string, unknown>[]}
                  />
                </Card>
                <Card title="Keys and indexes" icon="bi-key">
                  <div className="small">
                    <div className="mb-2">
                      <span className="fw-semibold">primary key: </span>
                      <span className="mono">{meta.primaryKey.join(", ") || "(none)"}</span>
                    </div>
                    <div className="mb-2">
                      <span className="fw-semibold">unique: </span>
                      <span className="mono">
                        {meta.unique.map((u) => `${u.name}(${u.columns.join(", ")})`).join("  ") || "(none)"}
                      </span>
                    </div>
                    <div className="mb-2">
                      <span className="fw-semibold">foreign keys: </span>
                      <span className="mono">
                        {meta.foreignKeys.map((f) => `${f.column} -> ${f.refTable}.${f.refColumn}`).join("  ") ||
                          "(none)"}
                      </span>
                    </div>
                    <div className="fw-semibold">indexes</div>
                    <ul className="mono mb-0">
                      {meta.indexes.map((i) => (
                        <li key={i.name}>{i.def}</li>
                      ))}
                    </ul>
                  </div>
                </Card>
              </>
            ))}

          {tab === "rows" &&
            (!table ? (
              <Empty icon="bi-table">Pick a table</Empty>
            ) : (
              <>
                <Card
                  title={table}
                  icon="bi-table"
                  actions={
                    <>
                      <span className="small text-secondary">
                        {data ? `${data.total} rows · ${fmtMs(data.durationMs)}` : ""}
                      </span>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-primary"
                        onClick={() => {
                          setInsertMode(true);
                          setSelectedRow(null);
                          setEditValues({});
                        }}
                      >
                        <i className="bi bi-plus-lg me-1" aria-hidden="true" />
                        Insert
                      </button>
                      <button type="button" className="btn btn-sm btn-outline-secondary" onClick={loadRows} disabled={busy}>
                        <i className="bi bi-arrow-clockwise" aria-hidden="true" />
                        <span className="ms-1">
                          <Spinner show={busy} />
                        </span>
                      </button>
                    </>
                  }
                  bodyClass="card-body p-2"
                >
                  <div className="row g-2 mb-2">
                    <div className="col-md-3">
                      <select
                        className="form-select form-select-sm"
                        value={filterCol}
                        onChange={(e) => setFilterCol(e.target.value)}
                      >
                        <option value="">Filter column</option>
                        {(data?.columns ?? []).map((c) => (
                          <option key={c.column_name} value={c.column_name}>
                            {c.column_name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="col-md-3">
                      <input
                        className="form-control form-control-sm"
                        placeholder="contains"
                        value={filterVal}
                        onChange={(e) => setFilterVal(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && loadRows()}
                      />
                    </div>
                    <div className="col-md-3">
                      <select
                        className="form-select form-select-sm"
                        value={orderBy}
                        onChange={(e) => setOrderBy(e.target.value)}
                      >
                        <option value="">Order by (auto)</option>
                        {(data?.columns ?? []).map((c) => (
                          <option key={c.column_name} value={c.column_name}>
                            {c.column_name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="col-md-3 d-flex gap-2">
                      <select
                        className="form-select form-select-sm"
                        value={orderDir}
                        onChange={(e) => setOrderDir(e.target.value as "asc" | "desc")}
                      >
                        <option value="desc">desc</option>
                        <option value="asc">asc</option>
                      </select>
                      <select
                        className="form-select form-select-sm"
                        value={limit}
                        onChange={(e) => setLimit(Number(e.target.value))}
                      >
                        {[25, 50, 100, 250].map((n) => (
                          <option key={n} value={n}>
                            {n}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <DataTable
                    columns={(data?.columns ?? []).map((c) => c.column_name)}
                    rows={data?.rows ?? []}
                    onRowClick={(row) => {
                      setSelectedRow(row);
                      setInsertMode(false);
                      setEditValues(
                        Object.fromEntries(Object.entries(row).map(([k, v]) => [k, v == null ? "" : cellText(v)])),
                      );
                    }}
                  />

                  <div className="d-flex align-items-center gap-2 mt-2">
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-secondary"
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - limit))}
                    >
                      <i className="bi bi-chevron-left" aria-hidden="true" />
                    </button>
                    <span className="small text-secondary">
                      {offset + 1}-{Math.min(offset + limit, data?.total ?? 0)} of {data?.total ?? 0}
                    </span>
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-secondary"
                      disabled={(data?.total ?? 0) <= offset + limit}
                      onClick={() => setOffset(offset + limit)}
                    >
                      <i className="bi bi-chevron-right" aria-hidden="true" />
                    </button>
                    <span className="small mono text-secondary ms-auto text-truncate" title={data?.sql}>
                      {data?.sql}
                    </span>
                  </div>
                </Card>

                {(selectedRow || insertMode) && (
                  <Card
                    title={insertMode ? `Insert into ${table}` : `Edit row in ${table}`}
                    icon={insertMode ? "bi-plus-square" : "bi-pencil-square"}
                    actions={
                      <button
                        type="button"
                        className="btn-close"
                        aria-label="Close"
                        onClick={() => {
                          setSelectedRow(null);
                          setInsertMode(false);
                        }}
                      />
                    }
                  >
                    <div className="row g-2">
                      {(data?.columns ?? []).map((c) => (
                        <Field
                          key={c.column_name}
                          label={c.column_name}
                          hint={`${c.udt_name}${c.is_nullable === "YES" ? "" : " not null"}`}
                          className="col-md-6"
                        >
                          <input
                            className="form-control form-control-sm mono"
                            value={editValues[c.column_name] ?? ""}
                            placeholder={c.column_default ?? ""}
                            onChange={(e) => setEditValues({ ...editValues, [c.column_name]: e.target.value })}
                          />
                        </Field>
                      ))}
                    </div>

                    <div className="d-flex gap-2 mt-3">
                      {insertMode ? (
                        <button
                          type="button"
                          className="btn btn-sm btn-primary"
                          disabled={busy}
                          onClick={() => mutate({ action: "insert", table, values: editValues })}
                        >
                          <i className="bi bi-plus-lg me-1" aria-hidden="true" />
                          Insert
                        </button>
                      ) : (
                        <>
                          <ConfirmButton
                            label="Save changes"
                            icon="bi-save"
                            className="btn btn-sm btn-primary"
                            message={`Update this row in ${table}. Changed values are written as-is; empty means NULL.`}
                            onConfirm={() =>
                              mutate({
                                action: "update",
                                table,
                                values: editValues,
                                where: pkWhere(selectedRow as Record<string, unknown>),
                              })
                            }
                          />
                          <ConfirmButton
                            label="Delete row"
                            icon="bi-trash"
                            message={`Permanently delete this row from ${table}. Rows referencing it may be deleted too if the foreign key cascades.`}
                            onConfirm={() =>
                              mutate({ action: "delete", table, where: pkWhere(selectedRow as Record<string, unknown>) })
                            }
                          />
                        </>
                      )}
                    </div>

                    {selectedRow && (
                      <details className="mt-3">
                        <summary className="small text-secondary">stored value</summary>
                        <Json value={selectedRow} />
                      </details>
                    )}
                  </Card>
                )}
              </>
            ))}
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------- sql runner */

function SqlRunner() {
  const [sql, setSql] = useState("select table_name, column_name, udt_name\nfrom information_schema.columns\nwhere table_schema = 'public'\norder by table_name, ordinal_position\nlimit 50;");
  const [allowWrite, setAllowWrite] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    const res = await callConsole<Record<string, unknown>>("/api/pg/query", { json: { sql, allowWrite } });
    if (res.error) {
      setError(String(res.error));
      setResult(null);
    } else setResult(res);
    setBusy(false);
  };

  const samples: [string, string][] = [
    ["Session interactions", "select role, intent, left(text, 80) as text, timestamp\nfrom interaction_logs order by timestamp desc limit 20;"],
    ["Mastery by student", "select s.full_name, c.slug, m.mastery, m.confidence, m.n_attempts, m.last_seen\nfrom mastery_scores m join students s on s.id = m.student_id\njoin concepts c on c.id = m.concept_id order by m.last_seen desc limit 30;"],
    ["Quiz funnel", "select q.id, q.status, q.total_questions, q.correct_count, q.final_score,\n       count(a.id) as attempts\nfrom quiz_sessions q left join quiz_attempts a on a.quiz_session_id = q.id\ngroup by q.id order by q.started_at desc limit 20;"],
    ["Chunk dimensions", "select source, count(*) as chunks, min(vector_dims(embedding)) as dim\nfrom curriculum_chunks group by source;"],
    ["Checkpoint threads", "select thread_id, count(*) as steps, max(checkpoint->>'ts') as last_ts\nfrom checkpoints group by thread_id order by last_ts desc limit 20;"],
  ];

  return (
    <>
      <Card
        title="SQL"
        icon="bi-terminal"
        actions={
          <div className="form-check form-switch mb-0">
            <input
              className="form-check-input"
              type="checkbox"
              id="allowwrite"
              checked={allowWrite}
              onChange={(e) => setAllowWrite(e.target.checked)}
            />
            <label className="form-check-label small text-danger" htmlFor="allowwrite">
              write mode
            </label>
          </div>
        }
      >
        <div className="d-flex flex-wrap gap-1 mb-2">
          {samples.map(([label, s]) => (
            <button key={label} type="button" className="btn btn-sm btn-outline-secondary py-0" onClick={() => setSql(s)}>
              {label}
            </button>
          ))}
        </div>

        <textarea
          className="form-control mono"
          rows={7}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void run();
            }
          }}
        />
        <div className="d-flex align-items-center gap-2 mt-2">
          <button type="button" className="btn btn-sm btn-primary" onClick={run} disabled={busy}>
            <i className="bi bi-play-fill me-1" aria-hidden="true" />
            Run
          </button>
          <Spinner show={busy} />
          <span className="small text-secondary ms-auto">Ctrl+Enter</span>
        </div>
      </Card>

      <ErrorNote error={error} />

      {result && (
        <Card
          title="Result"
          icon="bi-table"
          actions={
            <span className="small text-secondary">
              {String(result.command)} · {String(result.rowCount)} rows · {fmtMs(Number(result.durationMs))}
            </span>
          }
          bodyClass="card-body p-2"
        >
          <DataTable
            columns={(result.fields as string[]) ?? []}
            rows={(result.rows as Record<string, unknown>[]) ?? []}
          />
        </Card>
      )}
    </>
  );
}
