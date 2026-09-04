import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Collection name is a module constant in rag/stores/qdrant_store.py:22. */
const COLLECTION = "kodmod_curriculum";

async function call(base: string, path: string, init?: RequestInit) {
  const t0 = Date.now();
  const res = await fetch(`${base}${path}`, { ...init, cache: "no-store" });
  const body = await res.json().catch(() => null);
  publish("http", `qdrant ${init?.method ?? "GET"} ${path} -> ${res.status}`, {
    durationMs: Date.now() - t0,
    level: res.ok ? "info" : "warn",
  });
  return { status: res.status, ok: res.ok, body };
}

export async function GET(req: NextRequest) {
  const profile = await activeProfile();
  const scroll = req.nextUrl.searchParams.get("scroll") === "1";

  try {
    const collections = await call(profile.qdrantUrl, "/collections");
    const info = await call(profile.qdrantUrl, `/collections/${COLLECTION}`);
    let points: unknown = null;
    if (scroll && info.ok) {
      const r = await call(profile.qdrantUrl, `/collections/${COLLECTION}/points/scroll`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ limit: 25, with_payload: true, with_vector: false }),
      });
      points = r.body;
    }
    return NextResponse.json({
      url: profile.qdrantUrl,
      collection: COLLECTION,
      collections: collections.body,
      info: info.body,
      infoStatus: info.status,
      points,
    });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message, url: profile.qdrantUrl }, { status: 502 });
  }
}

export async function DELETE() {
  const profile = await activeProfile();
  const res = await call(profile.qdrantUrl, `/collections/${COLLECTION}`, { method: "DELETE" });
  publish("system", `qdrant collection ${COLLECTION} dropped`, { level: "warn" });
  return NextResponse.json(res);
}
