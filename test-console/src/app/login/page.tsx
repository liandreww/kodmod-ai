"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, Copy, DataTable, Empty, ErrorNote, Field, Json, Spinner, StatusDot } from "@/components/ui";
import { callApi, callConsole } from "@/lib/client";

interface Identity {
  id: string;
  full_name: string;
  email: string | null;
  [k: string]: unknown;
}

interface SessionState {
  session: {
    token: string;
    sub: string;
    role: string;
    displayName: string;
    profile: string;
    note?: string;
    inspect?: Inspect;
  } | null;
  profile: { name: string; jwtAlg: string; jwtSecretMasked: string; apiUrl: string };
}

interface Inspect {
  header: Record<string, unknown> | null;
  payload: Record<string, unknown> | null;
  expiresAt: string | null;
  expiresInSeconds: number | null;
  valid: boolean;
  error?: string;
}

type Tab = "signin" | "register" | "advanced";

export default function LoginPage() {
  const [tab, setTab] = useState<Tab>("signin");
  const [state, setState] = useState<SessionState | null>(null);
  const [students, setStudents] = useState<Identity[]>([]);
  const [teachers, setTeachers] = useState<Identity[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, ids] = await Promise.all([
        callConsole<SessionState>("/api/session"),
        callConsole<{ students: Identity[]; teachers: Identity[] }>("/api/identities"),
      ]);
      setState(s);
      setStudents(ids.students ?? []);
      setTeachers(ids.teachers ?? []);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const signIn = async (payload: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await callConsole<{ ok?: boolean; error?: string }>("/api/session", {
        json: { action: "signin", ...payload },
      });
      if (res.error) setError(res.error);
      window.dispatchEvent(new Event("kodmod:session-changed"));
      await load();
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    await callConsole("/api/session", { json: { action: "signout" } });
    window.dispatchEvent(new Event("kodmod:session-changed"));
    await load();
  };

  const inspect = state?.session?.inspect;
  const expSeconds = inspect?.payload?.exp ? Number(inspect.payload.exp) - Math.floor(now / 1000) : null;

  return (
    <>
      <h5 className="mb-3">Identity</h5>

      <div className="alert alert-secondary py-2 px-3 small d-flex gap-2 align-items-start">
        <i className="bi bi-info-circle mt-1" aria-hidden="true" />
        <span>
          The backend has no login route and no password column. Signing in mints an HS256 token whose{" "}
          <code>sub</code> is a real <code>students</code> or <code>teachers</code> row id, signed with the active
          profile&apos;s <code>JWT_SECRET</code>.
        </span>
      </div>

      <ErrorNote error={error} />

      <div className="split">
        <div>
          <ul className="nav nav-tabs mb-3">
            {(
              [
                ["signin", "Sign in", "bi-box-arrow-in-right"],
                ["register", "Register student", "bi-person-plus"],
                ["advanced", "Token workbench", "bi-key"],
              ] as [Tab, string, string][]
            ).map(([id, label, icon]) => (
              <li className="nav-item" key={id}>
                <button
                  type="button"
                  className={`nav-link ${tab === id ? "active" : ""}`}
                  onClick={() => setTab(id)}
                >
                  <i className={`bi ${icon} me-1`} aria-hidden="true" />
                  {label}
                </button>
              </li>
            ))}
          </ul>

          {tab === "signin" && (
            <SignInTab students={students} teachers={teachers} onSignIn={signIn} busy={busy} onReload={load} />
          )}
          {tab === "register" && <RegisterTab onDone={load} onSignIn={signIn} />}
          {tab === "advanced" && <AdvancedTab onSignIn={signIn} students={students} teachers={teachers} />}
        </div>

        <div>
          <Card
            title="Current token"
            icon="bi-shield-lock"
            actions={
              state?.session ? (
                <button type="button" className="btn btn-sm btn-outline-danger" onClick={signOut}>
                  <i className="bi bi-box-arrow-right me-1" aria-hidden="true" />
                  Sign out
                </button>
              ) : null
            }
          >
            {!state?.session ? (
              <Empty icon="bi-person-slash">Not signed in</Empty>
            ) : (
              <>
                <div className="d-flex align-items-center gap-2 mb-2">
                  <StatusDot state={inspect?.valid ? "ok" : "bad"} />
                  <span className="fw-semibold">{state.session.displayName}</span>
                  <span className="badge bg-secondary">{state.session.role}</span>
                  {expSeconds !== null && (
                    <span className={`badge ${expSeconds > 0 ? "bg-success" : "bg-danger"}`}>
                      {expSeconds > 0 ? `expires in ${formatDuration(expSeconds)}` : "expired"}
                    </span>
                  )}
                </div>

                {state.session.note && (
                  <div className="alert alert-warning py-1 px-2 small mb-2">{state.session.note}</div>
                )}
                {inspect?.error && (
                  <div className="alert alert-danger py-1 px-2 small mb-2 mono">
                    signature check: {inspect.error}
                  </div>
                )}

                <div className="input-group input-group-sm mb-2">
                  <input className="form-control mono" readOnly value={state.session.token} />
                  <Copy value={state.session.token} />
                </div>

                <div className="small text-secondary mb-1">Claims</div>
                <Json value={inspect?.payload ?? {}} />
                <div className="small text-secondary mb-1 mt-2">Header</div>
                <Json value={inspect?.header ?? {}} />
              </>
            )}
          </Card>

          <Card title="Signing key" icon="bi-key">
            <table className="table table-sm mono mb-0">
              <tbody>
                <tr>
                  <td className="text-secondary">profile</td>
                  <td>{state?.profile.name}</td>
                </tr>
                <tr>
                  <td className="text-secondary">alg</td>
                  <td>{state?.profile.jwtAlg}</td>
                </tr>
                <tr>
                  <td className="text-secondary">secret</td>
                  <td className="text-break">{state?.profile.jwtSecretMasked}</td>
                </tr>
                <tr>
                  <td className="text-secondary">api</td>
                  <td className="text-break">{state?.profile.apiUrl}</td>
                </tr>
              </tbody>
            </table>
          </Card>
        </div>
      </div>
    </>
  );
}

function formatDuration(seconds: number): string {
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}

/* --------------------------------------------------------------- sign in */

function SignInTab({
  students,
  teachers,
  onSignIn,
  busy,
  onReload,
}: {
  students: Identity[];
  teachers: Identity[];
  onSignIn: (p: Record<string, unknown>) => Promise<void>;
  busy: boolean;
  onReload: () => void;
}) {
  const [role, setRole] = useState<"student" | "teacher">("student");
  const rows = role === "student" ? students : teachers;

  const columns =
    role === "student"
      ? ["full_name", "email", "grade_level", "accessibility_profile", "mastery_rows", "sessions", "quizzes", "id"]
      : ["full_name", "email", "subject_specialty", "classrooms", "id"];

  return (
    <Card
      title={`Rows in ${role === "student" ? "students" : "teachers"}`}
      icon="bi-people"
      actions={
        <>
          <div className="btn-group btn-group-sm">
            <button
              type="button"
              className={`btn ${role === "student" ? "btn-primary" : "btn-outline-secondary"}`}
              onClick={() => setRole("student")}
            >
              Students
            </button>
            <button
              type="button"
              className={`btn ${role === "teacher" ? "btn-primary" : "btn-outline-secondary"}`}
              onClick={() => setRole("teacher")}
            >
              Teachers
            </button>
          </div>
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={onReload}>
            <i className="bi bi-arrow-clockwise" aria-hidden="true" />
          </button>
          <Spinner show={busy} />
        </>
      }
      bodyClass="card-body p-0"
    >
      {rows.length === 0 ? (
        <Empty icon="bi-person-x">
          No {role} rows. Create them on the Fixtures page, or register a student here.
        </Empty>
      ) : (
        <DataTable
          columns={columns}
          rows={rows as unknown as Record<string, unknown>[]}
          onRowClick={(row) =>
            onSignIn({
              sub: String(row.id),
              role,
              displayName: String(row.full_name ?? row.id),
              ttlSeconds: 3600,
            })
          }
        />
      )}
    </Card>
  );
}

/* -------------------------------------------------------------- register */

function RegisterTab({
  onDone,
  onSignIn,
}: {
  onDone: () => void;
  onSignIn: (p: Record<string, unknown>) => Promise<void>;
}) {
  const [form, setForm] = useState({
    full_name: "Siswa Manual",
    email: `manual+${Date.now()}@kodmod.test`,
    grade_level: "6",
    accessibility_profile: "blind",
    preferred_language: "id",
  });
  const [result, setResult] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    const res = await callApi<Record<string, unknown>>("student", {
      method: "POST",
      auth: "none",
      json: { ...form, voice_settings: {} },
    });
    setResult(res);
    if (res.status === 201 && res.body?.id) {
      await onSignIn({
        sub: String(res.body.id),
        role: "student",
        displayName: String(res.body.full_name ?? form.full_name),
        ttlSeconds: 3600,
      });
      onDone();
    } else {
      setError(`POST /student returned ${res.status}`);
    }
    setBusy(false);
  };

  return (
    <Card title="POST /student" icon="bi-person-plus">
      <div className="alert alert-secondary py-1 px-2 small">
        Unauthenticated by design — this is the bootstrap path
        (<span className="mono">tests/api/test_authz_inventory.py:24</span>).
      </div>

      <div className="row g-2 mb-3">
        <Field label="full_name" className="col-md-6">
          <input
            className="form-control form-control-sm"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          />
        </Field>
        <Field label="email" hint="unique, 409 on repeat" className="col-md-6">
          <input
            className="form-control form-control-sm"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </Field>
        <Field label="grade_level" className="col-md-4">
          <input
            className="form-control form-control-sm"
            value={form.grade_level}
            onChange={(e) => setForm({ ...form, grade_level: e.target.value })}
          />
        </Field>
        <Field label="accessibility_profile" className="col-md-4">
          <select
            className="form-select form-select-sm"
            value={form.accessibility_profile}
            onChange={(e) => setForm({ ...form, accessibility_profile: e.target.value })}
          >
            <option value="blind">blind</option>
            <option value="low_vision">low_vision</option>
            <option value="sighted">sighted</option>
          </select>
        </Field>
        <Field label="preferred_language" className="col-md-4">
          <select
            className="form-select form-select-sm"
            value={form.preferred_language}
            onChange={(e) => setForm({ ...form, preferred_language: e.target.value })}
          >
            <option value="id">id</option>
            <option value="en">en</option>
          </select>
        </Field>
      </div>

      <button type="button" className="btn btn-sm btn-primary" onClick={submit} disabled={busy}>
        <i className="bi bi-person-plus me-1" aria-hidden="true" />
        Create and sign in
        <span className="ms-2">
          <Spinner show={busy} />
        </span>
      </button>

      <ErrorNote error={error} />
      {result != null && (
        <div className="mt-3">
          <Json value={result} />
        </div>
      )}
    </Card>
  );
}

/* -------------------------------------------------------------- advanced */

function AdvancedTab({
  onSignIn,
  students,
  teachers,
}: {
  onSignIn: (p: Record<string, unknown>) => Promise<void>;
  students: Identity[];
  teachers: Identity[];
}) {
  const [sub, setSub] = useState("");
  const [role, setRole] = useState("student");
  const [ttl, setTtl] = useState(3600);
  const [secretOverride, setSecretOverride] = useState("");
  const [expiredBy, setExpiredBy] = useState(0);
  const [algNone, setAlgNone] = useState(false);
  const [rawToken, setRawToken] = useState("");

  const presets: { label: string; expect: string; apply: () => void }[] = [
    {
      label: "Valid student, 1h",
      expect: "200",
      apply: () => {
        setRole("student");
        setTtl(3600);
        setSecretOverride("");
        setExpiredBy(0);
        setAlgNone(false);
      },
    },
    {
      label: "Expired token",
      expect: "401 Token expired",
      apply: () => {
        setTtl(60);
        setExpiredBy(7200);
        setSecretOverride("");
        setAlgNone(false);
      },
    },
    {
      label: "Wrong signing secret",
      expect: "401 Invalid token",
      apply: () => {
        setSecretOverride("definitely-not-the-server-secret");
        setExpiredBy(0);
        setAlgNone(false);
      },
    },
    {
      label: "alg=none",
      expect: "401 Invalid token",
      apply: () => {
        setAlgNone(true);
        setSecretOverride("");
        setExpiredBy(0);
      },
    },
    {
      label: "Unknown sub",
      expect: "404 Student not found",
      apply: () => {
        setSub("00000000-0000-0000-0000-0000000000ff");
        setRole("student");
        setSecretOverride("");
        setExpiredBy(0);
        setAlgNone(false);
      },
    },
    {
      label: "Teacher token on student routes",
      expect: "403 Not a student token",
      apply: () => {
        setRole("teacher");
        setSecretOverride("");
        setExpiredBy(0);
        setAlgNone(false);
      },
    },
  ];

  return (
    <>
      <Card title="Mint a token" icon="bi-key">
        <div className="row g-2 mb-3">
          <Field label="sub" hint="must match a real row id" className="col-md-8">
            <input
              className="form-control form-control-sm mono"
              value={sub}
              placeholder="uuid"
              onChange={(e) => setSub(e.target.value)}
            />
          </Field>
          <Field label="role" className="col-md-4">
            <select className="form-select form-select-sm" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="student">student</option>
              <option value="teacher">teacher</option>
              <option value="admin">admin (invalid on purpose)</option>
            </select>
          </Field>
          <Field label="ttl seconds" className="col-md-3">
            <input
              type="number"
              className="form-control form-control-sm"
              value={ttl}
              onChange={(e) => setTtl(Number(e.target.value))}
            />
          </Field>
          <Field label="back-date by seconds" hint="forces expiry" className="col-md-3">
            <input
              type="number"
              className="form-control form-control-sm"
              value={expiredBy}
              onChange={(e) => setExpiredBy(Number(e.target.value))}
            />
          </Field>
          <Field label="secret override" hint="blank = profile secret" className="col-md-6">
            <input
              className="form-control form-control-sm mono"
              value={secretOverride}
              onChange={(e) => setSecretOverride(e.target.value)}
            />
          </Field>
        </div>

        <div className="form-check form-switch mb-3">
          <input
            className="form-check-input"
            type="checkbox"
            id="algnone"
            checked={algNone}
            onChange={(e) => setAlgNone(e.target.checked)}
          />
          <label className="form-check-label small" htmlFor="algnone">
            alg=none (unsigned)
          </label>
        </div>

        <div className="d-flex flex-wrap gap-2 mb-3">
          {presets.map((p) => (
            <button
              key={p.label}
              type="button"
              className="btn btn-sm btn-outline-secondary"
              title={`expects ${p.expect}`}
              onClick={p.apply}
            >
              {p.label}
              <span className="badge bg-secondary ms-2">{p.expect}</span>
            </button>
          ))}
        </div>

        <div className="d-flex gap-2 flex-wrap">
          <select
            className="form-select form-select-sm"
            style={{ maxWidth: 320 }}
            onChange={(e) => setSub(e.target.value)}
            value=""
          >
            <option value="">Pick an existing id</option>
            <optgroup label="students">
              {students.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.full_name}
                </option>
              ))}
            </optgroup>
            <optgroup label="teachers">
              {teachers.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.full_name}
                </option>
              ))}
            </optgroup>
          </select>

          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!sub}
            onClick={() =>
              onSignIn({
                sub,
                role,
                displayName: sub.slice(0, 8),
                ttlSeconds: ttl,
                secretOverride: secretOverride || undefined,
                expiredBySeconds: expiredBy || undefined,
                algNone,
              })
            }
          >
            <i className="bi bi-key me-1" aria-hidden="true" />
            Mint and use
          </button>
        </div>
      </Card>

      <Card title="Use a pasted token" icon="bi-clipboard-check">
        <div className="input-group input-group-sm">
          <input
            className="form-control mono"
            placeholder="eyJhbGciOi..."
            value={rawToken}
            onChange={(e) => setRawToken(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-outline-primary"
            disabled={!rawToken}
            onClick={() => onSignIn({ rawToken, sub: "(pasted)", role: "unknown", displayName: "pasted token" })}
          >
            Use
          </button>
        </div>
      </Card>
    </>
  );
}
