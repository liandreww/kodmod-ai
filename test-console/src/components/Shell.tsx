"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { LogList, useActivity } from "./activity";
import { StatusDot } from "./ui";

const NAV: { section: string; items: { href: string; label: string; icon: string }[] }[] = [
  {
    section: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: "bi-speedometer2" },
      { href: "/login", label: "Identity", icon: "bi-person-badge" },
    ],
  },
  {
    section: "Features",
    items: [
      { href: "/tutor", label: "Tutor", icon: "bi-chat-left-text" },
      { href: "/quiz", label: "Quiz", icon: "bi-list-check" },
      { href: "/exercise", label: "Exercise", icon: "bi-pencil-square" },
      { href: "/content", label: "Content & RAG", icon: "bi-book" },
      { href: "/analytics", label: "Analytics", icon: "bi-bar-chart" },
      { href: "/voice", label: "Audio upload", icon: "bi-file-earmark-music" },
    ],
  },
  {
    section: "Observability",
    items: [
      { href: "/observe", label: "Live activity", icon: "bi-activity" },
      { href: "/graph", label: "Graph trace", icon: "bi-diagram-3" },
    ],
  },
  {
    section: "Datastores",
    items: [
      { href: "/db", label: "Postgres", icon: "bi-database" },
      { href: "/db/redis", label: "Redis", icon: "bi-hdd-stack" },
      { href: "/db/vectors", label: "Vectors", icon: "bi-grid-3x3" },
    ],
  },
  {
    section: "Maintenance",
    items: [{ href: "/admin", label: "Fixtures & reset", icon: "bi-tools" }],
  },
];

interface Health {
  profile: { name: string; apiUrl: string };
  checks: { name: string; ok: boolean; detail: string }[];
  warnings: string[];
}

interface SessionInfo {
  session: { sub: string; role: string; displayName: string; profile: string; note?: string } | null;
  profile: { name: string; apiUrl: string; jwtSecretMasked: string };
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { events, connected } = useActivity();
  const [drawer, setDrawer] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [taps, setTaps] = useState<Record<string, { running: boolean }>>({});

  const refreshSession = useCallback(async () => {
    try {
      setInfo(await (await fetch("/api/session", { cache: "no-store" })).json());
    } catch {
      /* offline */
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await (await fetch("/api/health", { cache: "no-store" })).json());
    } catch {
      setHealth(null);
    }
  }, []);

  const refreshTaps = useCallback(async () => {
    try {
      setTaps(await (await fetch("/api/tap", { cache: "no-store" })).json());
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    void refreshSession();
    void refreshHealth();
    void refreshTaps();
    const t = setInterval(refreshHealth, 20_000);
    const onChange = () => {
      void refreshSession();
      void refreshHealth();
    };
    window.addEventListener("kodmod:session-changed", onChange);
    return () => {
      clearInterval(t);
      window.removeEventListener("kodmod:session-changed", onChange);
    };
  }, [refreshSession, refreshHealth, refreshTaps]);

  const switchProfile = async (name: string) => {
    await fetch("/api/profile", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
    window.dispatchEvent(new Event("kodmod:session-changed"));
    router.refresh();
  };

  const toggleTap = async (tap: string, on: boolean) => {
    setTaps((t) => ({ ...t, [tap]: { running: on } }));
    const res = await fetch("/api/tap", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ tap, on }),
    });
    setTaps(await res.json());
  };

  const apiOk = health?.checks.find((c) => c.name === "api.live")?.ok;
  const pgOk = health?.checks.find((c) => c.name === "postgres")?.ok;
  const redisOk = health?.checks.find((c) => c.name === "redis")?.ok;
  const profileName = info?.profile.name ?? health?.profile.name ?? "test";

  return (
    <div className="app-shell">
      <div className="app-brand">
        <i className="bi bi-terminal text-primary fs-5" aria-hidden="true" />
        <span className="fw-semibold">KODMOD Console</span>
      </div>

      <div className="app-topbar">
        <div className="btn-group btn-group-sm" role="group" aria-label="Backend profile">
          {["test", "dev"].map((p) => (
            <button
              key={p}
              type="button"
              className={`btn ${profileName === p ? "btn-primary" : "btn-outline-secondary"}`}
              onClick={() => switchProfile(p)}
              title={p === "test" ? "scripts/serve_test_api stack" : "make dev stack (.env)"}
            >
              {p}
            </button>
          ))}
        </div>

        <span className="vr mx-1" />

        <div className="d-flex align-items-center gap-3 small">
          <span className="d-flex align-items-center gap-1" title={health?.checks.find((c) => c.name === "api.live")?.detail}>
            <StatusDot state={apiOk === undefined ? "idle" : apiOk ? "ok" : "bad"} title="API" />
            API
          </span>
          <span className="d-flex align-items-center gap-1" title={health?.checks.find((c) => c.name === "postgres")?.detail}>
            <StatusDot state={pgOk === undefined ? "idle" : pgOk ? "ok" : "bad"} title="Postgres" />
            PG
          </span>
          <span className="d-flex align-items-center gap-1" title={health?.checks.find((c) => c.name === "redis")?.detail}>
            <StatusDot state={redisOk === undefined ? "idle" : redisOk ? "ok" : "bad"} title="Redis" />
            Redis
          </span>
        </div>

        {!!health?.warnings.length && (
          <i
            className="bi bi-exclamation-triangle-fill text-warning"
            title={health.warnings.join("\n")}
            aria-label="warnings"
          />
        )}

        <div className="ms-auto d-flex align-items-center gap-2">
          <div className="btn-group btn-group-sm" role="group" aria-label="Live taps">
            {(["sql", "redis", "apilog"] as const).map((t) => (
              <button
                key={t}
                type="button"
                className={`btn ${taps[t]?.running ? "btn-success" : "btn-outline-secondary"}`}
                onClick={() => toggleTap(t, !taps[t]?.running)}
                title={
                  t === "sql"
                    ? "Postgres statement log tap (ALTER SYSTEM log_statement)"
                    : t === "redis"
                      ? "Redis MONITOR tap"
                      : "Tail kodmod-ai/reports/api.log"
                }
              >
                <i
                  className={`bi ${t === "sql" ? "bi-database-fill-gear" : t === "redis" ? "bi-hdd-network" : "bi-file-text"}`}
                  aria-hidden="true"
                />
              </button>
            ))}
          </div>

          {info?.session ? (
            <Link href="/login" className="btn btn-sm btn-outline-primary d-flex align-items-center gap-1">
              <i className={`bi ${info.session.role === "teacher" ? "bi-person-workspace" : "bi-person"}`} aria-hidden="true" />
              <span>{info.session.displayName}</span>
              <span className="badge bg-secondary">{info.session.role}</span>
              {info.session.note && <i className="bi bi-exclamation-circle text-warning" title={info.session.note} />}
            </Link>
          ) : (
            <Link href="/login" className="btn btn-sm btn-outline-danger">
              <i className="bi bi-person-slash me-1" aria-hidden="true" />
              Not signed in
            </Link>
          )}

          <button
            type="button"
            className={`btn btn-sm ${drawer ? "btn-primary" : "btn-outline-secondary"}`}
            onClick={() => setDrawer((v) => !v)}
            title="Activity timeline"
          >
            <i className="bi bi-activity" aria-hidden="true" />
            <span className="ms-1">{events.length}</span>
            <StatusDot state={connected ? "ok" : "bad"} />
          </button>
        </div>
      </div>

      <nav className="app-sidebar">
        {NAV.map((group) => (
          <div key={group.section}>
            <div className="nav-section">{group.section}</div>
            {group.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-link ${pathname === item.href ? "active" : ""}`}
              >
                <i className={`bi ${item.icon}`} aria-hidden="true" />
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>

      <main className="app-main">{children}</main>

      {drawer && (
        <>
          <div className="activity-backdrop" onClick={() => setDrawer(false)} />
          <aside className="activity-drawer">
            <div className="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
              <span className="fw-semibold d-flex align-items-center gap-2">
                <i className="bi bi-activity" aria-hidden="true" />
                Activity
              </span>
              <span className="d-flex align-items-center gap-2">
                <Link href="/observe" className="btn btn-sm btn-outline-secondary" onClick={() => setDrawer(false)}>
                  <i className="bi bi-arrows-fullscreen" aria-hidden="true" />
                </Link>
                <button type="button" className="btn-close" aria-label="Close" onClick={() => setDrawer(false)} />
              </span>
            </div>
            <div className="flex-grow-1 p-2 overflow-hidden">
              <LogList events={events.slice(-500)} height="100%" />
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
