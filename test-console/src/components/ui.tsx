"use client";

import { useState, type ReactNode } from "react";

/* ------------------------------------------------------------------ cards */

export function Card({
  title,
  icon,
  actions,
  children,
  bodyClass = "card-body",
}: {
  title?: ReactNode;
  icon?: string;
  actions?: ReactNode;
  children: ReactNode;
  bodyClass?: string;
}) {
  return (
    <div className="card mb-3">
      {title && (
        <div className="card-header d-flex align-items-center justify-content-between py-2">
          <span className="d-flex align-items-center gap-2 fw-semibold">
            {icon && <i className={`bi ${icon}`} aria-hidden="true" />}
            {title}
          </span>
          {actions && <span className="d-flex align-items-center gap-2">{actions}</span>}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ atoms */

export function StatusDot({ state, title }: { state: "ok" | "bad" | "warn" | "idle"; title?: string }) {
  const cls =
    state === "ok" ? "bg-success" : state === "bad" ? "bg-danger" : state === "warn" ? "bg-warning" : "bg-secondary";
  return <span className={`dot ${cls}`} title={title} aria-label={title ?? state} />;
}

export function Spinner({ show }: { show: boolean }) {
  if (!show) return null;
  return <span className="spinner-border spinner-border-sm" role="status" aria-label="working" />;
}

export function StatusBadge({ status }: { status?: number }) {
  if (status === undefined) return null;
  const cls = status < 300 ? "bg-success" : status < 400 ? "bg-info" : status < 500 ? "bg-warning text-dark" : "bg-danger";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function Copy({ value, label }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-sm btn-outline-secondary"
      title="Copy"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {
          /* clipboard blocked */
        }
      }}
    >
      <i className={`bi ${done ? "bi-check2" : "bi-clipboard"}`} aria-hidden="true" />
      {label && <span className="ms-1">{label}</span>}
    </button>
  );
}

export function Empty({ icon = "bi-inbox", children }: { icon?: string; children: ReactNode }) {
  return (
    <div className="text-center text-secondary py-4">
      <i className={`bi ${icon} fs-3 d-block mb-2`} aria-hidden="true" />
      <div className="small">{children}</div>
    </div>
  );
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return (
    <div className="alert alert-danger py-2 px-3 mb-2 small mono" role="alert">
      {error}
    </div>
  );
}

/* ------------------------------------------------------------------ forms */

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="form-label mb-1 small fw-semibold">
        {label}
        {hint && <span className="text-secondary fw-normal ms-1">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------- json */

export function Json({ value, tall = false }: { value: unknown; tall?: boolean }) {
  let text: string;
  if (typeof value === "string") text = value;
  else {
    try {
      text = JSON.stringify(value, null, 2);
    } catch {
      text = String(value);
    }
  }
  return <pre className={`out${tall ? " tall" : ""}`}>{text}</pre>;
}

export function Collapsible({
  summary,
  children,
  open = false,
  badge,
}: {
  summary: ReactNode;
  children: ReactNode;
  open?: boolean;
  badge?: ReactNode;
}) {
  const [isOpen, setOpen] = useState(open);
  return (
    <div className="border rounded mb-2">
      <button
        type="button"
        className="btn btn-sm w-100 text-start d-flex align-items-center justify-content-between px-2 py-1"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="d-flex align-items-center gap-2">
          <i className={`bi ${isOpen ? "bi-chevron-down" : "bi-chevron-right"}`} aria-hidden="true" />
          {summary}
        </span>
        {badge}
      </button>
      {isOpen && <div className="px-2 pb-2">{children}</div>}
    </div>
  );
}

/* --------------------------------------------------------------- confirm */

export function ConfirmButton({
  label,
  icon = "bi-exclamation-triangle",
  message,
  onConfirm,
  className = "btn btn-sm btn-outline-danger",
  disabled,
}: {
  label: string;
  icon?: string;
  message: string;
  onConfirm: () => void | Promise<void>;
  className?: string;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <>
      <button type="button" className={className} disabled={disabled || busy} onClick={() => setAsking(true)}>
        <i className={`bi ${icon} me-1`} aria-hidden="true" />
        {label}
        {busy && <span className="spinner-border spinner-border-sm ms-2" role="status" />}
      </button>

      {asking && (
        <>
          <div className="modal d-block" tabIndex={-1} role="dialog">
            <div className="modal-dialog modal-dialog-centered">
              <div className="modal-content">
                <div className="modal-header py-2">
                  <h6 className="modal-title d-flex align-items-center gap-2">
                    <i className="bi bi-exclamation-triangle text-danger" aria-hidden="true" />
                    {label}
                  </h6>
                  <button type="button" className="btn-close" aria-label="Cancel" onClick={() => setAsking(false)} />
                </div>
                <div className="modal-body small">{message}</div>
                <div className="modal-footer py-2">
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => setAsking(false)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={async () => {
                      setAsking(false);
                      setBusy(true);
                      try {
                        await onConfirm();
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    {label}
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div className="modal-backdrop show" />
        </>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- tables */

export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (o.__kind === "vector") return `vector(${o.dim})`;
    if (o.__kind === "bytes") return `bytes(${o.bytes})`;
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function DataTable({
  columns,
  rows,
  onRowClick,
  activeIndex,
  emptyText = "No rows",
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  onRowClick?: (row: Record<string, unknown>, index: number) => void;
  activeIndex?: number;
  emptyText?: string;
}) {
  if (!rows.length) return <Empty>{emptyText}</Empty>;
  return (
    <div className="table-scroll">
      <table className="table table-sm table-hover table-bordered">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} className="text-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              className={activeIndex === i ? "table-active" : undefined}
              style={onRowClick ? { cursor: "pointer" } : undefined}
              onClick={() => onRowClick?.(row, i)}
            >
              {columns.map((c) => {
                const text = cellText(row[c]);
                return (
                  <td key={c} title={text.length > 60 ? text : undefined}>
                    <span className="cell-clip">{text}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
