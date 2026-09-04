import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { clientFor, readKey, scanKeys } from "@/lib/redis";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * The backend's whole short-term surface is
 *   kodmod:session:{session_id}:{last_response|tutoring_turns|tts_rate|quiz}
 * (memory/short_term.py:50), all with a 24h TTL. tutoring_turns is a list,
 * the rest are JSON strings.
 */
export async function GET(req: NextRequest) {
  const profile = await activeProfile();
  const sp = req.nextUrl.searchParams;
  const key = sp.get("key");

  if (key) {
    return NextResponse.json({ entry: await readKey(profile, key) });
  }

  const pattern = sp.get("pattern") || "kodmod:*";
  const withValues = sp.get("values") === "1";
  const keys = await scanKeys(profile, pattern, 500);
  const c = clientFor(profile);

  const entries = await Promise.all(
    keys.sort().map(async (k) => {
      if (withValues) return readKey(profile, k);
      const [type, ttl] = await Promise.all([c.type(k), c.ttl(k)]);
      return { key: k, type, ttl, size: 0, value: null };
    }),
  );

  // Group by session id so the UI can show one card per conversation.
  const sessions = new Map<string, string[]>();
  for (const k of keys) {
    const m = /^kodmod:session:([^:]+):(.+)$/.exec(k);
    if (!m) continue;
    if (!sessions.has(m[1])) sessions.set(m[1], []);
    sessions.get(m[1])!.push(m[2]);
  }

  return NextResponse.json({
    pattern,
    entries,
    sessions: Array.from(sessions.entries()).map(([id, subs]) => ({ sessionId: id, subs: subs.sort() })),
  });
}

export async function POST(req: NextRequest) {
  const profile = await activeProfile();
  const body = await req.json();
  const action = String(body.action ?? "");
  const c = clientFor(profile);

  try {
    if (action === "delete") {
      const n = await c.del(String(body.key));
      publish("console-redis", `DEL ${body.key} -> ${n}`);
      return NextResponse.json({ ok: true, deleted: n });
    }
    if (action === "deletePattern") {
      const pattern = String(body.pattern ?? "");
      if (!pattern || pattern === "*") {
        return NextResponse.json({ error: "refusing to delete on an empty or '*' pattern" }, { status: 400 });
      }
      const keys = await scanKeys(profile, pattern, 5000);
      const n = keys.length ? await c.del(...keys) : 0;
      publish("console-redis", `DEL ${pattern} -> ${n} keys`, { level: "warn", detail: { keys } });
      return NextResponse.json({ ok: true, deleted: n, keys });
    }
    if (action === "expire") {
      const n = await c.expire(String(body.key), Number(body.ttl));
      publish("console-redis", `EXPIRE ${body.key} ${body.ttl} -> ${n}`);
      return NextResponse.json({ ok: true, applied: n });
    }
    if (action === "set") {
      const ttl = Number(body.ttl ?? 0);
      const value = typeof body.value === "string" ? body.value : JSON.stringify(body.value);
      if (ttl > 0) await c.set(String(body.key), value, "EX", ttl);
      else await c.set(String(body.key), value);
      publish("console-redis", `SET ${body.key}`, { detail: { ttl } });
      return NextResponse.json({ ok: true });
    }
    return NextResponse.json({ error: `unknown action: ${action}` }, { status: 400 });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 400 });
  }
}
