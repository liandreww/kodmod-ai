import { NextResponse } from "next/server";
import { activeProfile, publicProfile } from "@/lib/profiles";
import { query } from "@/lib/pg";
import { clientFor } from "@/lib/redis";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Check {
  name: string;
  ok: boolean;
  detail: string;
  data?: unknown;
  durationMs: number;
}

async function timed(name: string, fn: () => Promise<{ detail: string; data?: unknown }>): Promise<Check> {
  const t0 = Date.now();
  try {
    const r = await fn();
    return { name, ok: true, detail: r.detail, data: r.data, durationMs: Date.now() - t0 };
  } catch (err) {
    return { name, ok: false, detail: (err as Error).message, durationMs: Date.now() - t0 };
  }
}

export async function GET() {
  const profile = await activeProfile();

  const [live, ready, version, pg, redis, qdrant, checkpointer] = await Promise.all([
    timed("api.live", async () => {
      const r = await fetch(`${profile.apiUrl}/live`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return { detail: "alive", data: await r.json() };
    }),
    timed("api.ready", async () => {
      const r = await fetch(`${profile.apiUrl}/ready`, { cache: "no-store" });
      const body = await r.json();
      if (body.status !== "ready") throw new Error(JSON.stringify(body.checks ?? body));
      return { detail: "ready", data: body };
    }),
    timed("api.version", async () => {
      const r = await fetch(`${profile.apiUrl}/version`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      return { detail: `${body.name} ${body.version} / ${body.env}`, data: body };
    }),
    timed("postgres", async () => {
      const r = await query(profile, "select current_database() as db, version() as v", [], { quiet: true });
      const row = r.rows[0] as { db: string; v: string };
      return { detail: `${row.db} / ${String(row.v).split(",")[0]}`, data: row };
    }),
    timed("redis", async () => {
      const c = clientFor(profile);
      const pong = await c.ping();
      const size = await c.dbsize();
      return { detail: `${pong}, ${size} keys`, data: { dbsize: size } };
    }),
    timed("qdrant", async () => {
      const r = await fetch(`${profile.qdrantUrl}/collections`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      const names = (body?.result?.collections ?? []).map((c: { name: string }) => c.name);
      return { detail: names.length ? names.join(", ") : "no collections", data: names };
    }),
    timed("checkpointer", async () => {
      const r = await query(
        profile,
        `select count(*)::int as n from information_schema.tables
          where table_schema = 'public' and table_name = 'checkpoints'`,
        [],
        { quiet: true },
      );
      const present = Number((r.rows[0] as { n: number }).n) > 0;
      if (!present) {
        throw new Error("no checkpoints table -- KODMOD_CHECKPOINTER=memory, graph trace unavailable");
      }
      const c = await query(
        profile,
        `select count(*)::int                as n,
                count(distinct thread_id)::int as threads,
                max(checkpoint->>'ts')       as newest
           from checkpoints`,
        [],
        { quiet: true },
      );
      const row = c.rows[0] as { n: number; threads: number; newest: string | null };
      const age = row.newest ? Math.round((Date.now() - Date.parse(row.newest)) / 60000) : null;
      return {
        detail:
          `${row.n} checkpoints across ${row.threads} threads` +
          (age === null ? "" : `, newest ${age} min ago`),
        data: row,
      };
    }),
  ]);

  const checks = [live, ready, version, pg, redis, qdrant, checkpointer];

  // Cross-check: does the running API actually match the selected profile?
  const warnings: string[] = [];
  const v = version.data as Record<string, string> | undefined;
  if (v) {
    if (profile.name === "test" && v.env !== "test") {
      warnings.push(`profile "test" selected but the API reports env="${v.env}"`);
    }
    if (profile.name === "dev" && v.env === "test") {
      warnings.push(`profile "dev" selected but the API reports env="test" (started via serve_test_api?)`);
    }
  }
  if (!checkpointer.ok) warnings.push(checkpointer.detail);

  return NextResponse.json({ profile: publicProfile(profile), checks, warnings });
}
