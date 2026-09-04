"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Card, Empty, ErrorNote, Json, Spinner, StatusDot } from "@/components/ui";
import { callConsole, fmtMs } from "@/lib/client";

interface Check {
  name: string;
  ok: boolean;
  detail: string;
  data?: unknown;
  durationMs: number;
}

interface HealthResponse {
  profile: Record<string, string>;
  checks: Check[];
  warnings: string[];
}

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const [h, c] = await Promise.all([
        callConsole<HealthResponse>("/api/health"),
        callConsole<{ counts: Record<string, number> }>("/api/pg/counts").catch(() => ({ counts: {} })),
      ]);
      setHealth(h);
      setCounts(c.counts ?? {});
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const appTables = Object.keys(counts).filter((t) => !t.startsWith("checkpoint")).sort();
  const cpTables = Object.keys(counts).filter((t) => t.startsWith("checkpoint")).sort();
  const versionData = health?.checks.find((c) => c.name === "api.version")?.data as Record<string, string> | undefined;

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Dashboard</h5>
        <button type="button" className="btn btn-sm btn-outline-primary" onClick={refresh} disabled={busy}>
          <i className="bi bi-arrow-clockwise me-1" aria-hidden="true" />
          Refresh
          <span className="ms-2">
            <Spinner show={busy} />
          </span>
        </button>
      </div>

      <ErrorNote error={error} />

      {health?.warnings.map((w) => (
        <div key={w} className="alert alert-warning py-2 px-3 small d-flex align-items-start gap-2" role="alert">
          <i className="bi bi-exclamation-triangle-fill" aria-hidden="true" />
          <span>{w}</span>
        </div>
      ))}

      <div className="split">
        <div>
          <Card title="Dependencies" icon="bi-hdd-network" bodyClass="card-body p-0">
            <div className="table-responsive">
              <table className="table table-sm mb-0">
                <tbody>
                  {(health?.checks ?? []).map((c) => (
                    <tr key={c.name}>
                      <td style={{ width: 30 }}>
                        <StatusDot state={c.ok ? "ok" : "bad"} title={c.ok ? "ok" : "failed"} />
                      </td>
                      <td className="mono" style={{ width: 130 }}>
                        {c.name}
                      </td>
                      <td className={`small ${c.ok ? "" : "text-danger"}`}>{c.detail}</td>
                      <td className="text-secondary small text-end" style={{ width: 80 }}>
                        {fmtMs(c.durationMs)}
                      </td>
                    </tr>
                  ))}
                  {!health && (
                    <tr>
                      <td colSpan={4}>
                        <Empty icon="bi-hourglass">Checking</Empty>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <Card
            title="Table row counts"
            icon="bi-database"
            actions={
              <Link href="/db" className="btn btn-sm btn-outline-secondary">
                <i className="bi bi-box-arrow-up-right me-1" aria-hidden="true" />
                Explorer
              </Link>
            }
          >
            {appTables.length === 0 ? (
              <Empty icon="bi-database-slash">
                No tables. Run the schema and seed from <Link href="/admin">Fixtures &amp; reset</Link>.
              </Empty>
            ) : (
              <>
                <div className="row row-cols-2 row-cols-md-4 row-cols-xl-6 g-2">
                  {appTables.map((t) => (
                    <div className="col" key={t}>
                      <Link
                        href={`/db?table=${t}`}
                        className="d-block border rounded p-2 text-decoration-none text-body h-100"
                      >
                        <div className="fs-5 fw-semibold">{counts[t]}</div>
                        <div className="small text-secondary text-truncate mono" title={t}>
                          {t}
                        </div>
                      </Link>
                    </div>
                  ))}
                </div>

                {cpTables.length > 0 && (
                  <>
                    <div className="text-secondary small mt-3 mb-2 text-uppercase">LangGraph checkpointer</div>
                    <div className="row row-cols-2 row-cols-md-4 g-2">
                      {cpTables.map((t) => (
                        <div className="col" key={t}>
                          <Link
                            href="/graph"
                            className="d-block border rounded p-2 text-decoration-none text-body h-100"
                          >
                            <div className="fs-5 fw-semibold">{counts[t]}</div>
                            <div className="small text-secondary text-truncate mono">{t}</div>
                          </Link>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </Card>
        </div>

        <div>
          <Card title="Active profile" icon="bi-sliders">
            <table className="table table-sm mono mb-0">
              <tbody>
                {Object.entries(health?.profile ?? {}).map(([k, v]) => (
                  <tr key={k}>
                    <td className="text-secondary">{k}</td>
                    <td className="text-break">{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {versionData && (
            <Card title="Backend build" icon="bi-info-circle">
              <Json value={versionData} />
            </Card>
          )}

          <Card title="Where to start" icon="bi-signpost-2">
            <div className="list-group list-group-flush small">
              <Link href="/admin" className="list-group-item list-group-item-action d-flex gap-2 align-items-center">
                <i className="bi bi-1-circle" aria-hidden="true" />
                Seed curriculum and create fixtures
              </Link>
              <Link href="/login" className="list-group-item list-group-item-action d-flex gap-2 align-items-center">
                <i className="bi bi-2-circle" aria-hidden="true" />
                Sign in as a student
              </Link>
              <Link href="/observe" className="list-group-item list-group-item-action d-flex gap-2 align-items-center">
                <i className="bi bi-3-circle" aria-hidden="true" />
                Turn on the SQL and Redis taps
              </Link>
              <Link href="/tutor" className="list-group-item list-group-item-action d-flex gap-2 align-items-center">
                <i className="bi bi-4-circle" aria-hidden="true" />
                Run a tutoring turn
              </Link>
              <Link href="/graph" className="list-group-item list-group-item-action d-flex gap-2 align-items-center">
                <i className="bi bi-5-circle" aria-hidden="true" />
                Inspect the graph trace
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
