import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { readSession } from "@/lib/session";
import { publish, trim } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Server-side pass-through to the FastAPI backend.
 *
 * Everything REST goes through here rather than browser -> FastAPI directly:
 * api/main.py sets allow_origins=["*"] together with allow_credentials=True,
 * which browsers reject on credentialed requests. Proxying also lets us record
 * every request/response pair into the activity timeline.
 *
 * Query flags consumed here (stripped before forwarding):
 *   __auth=none    send no Authorization header
 *   __token=<jwt>  send this token instead of the session one
 */
async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const profile = await activeProfile();
  const session = await readSession();

  const url = new URL(req.url);
  const authMode = url.searchParams.get("__auth");
  const tokenOverride = url.searchParams.get("__token");
  url.searchParams.delete("__auth");
  url.searchParams.delete("__token");

  const target = `${profile.apiUrl}/${path.join("/")}${url.search}`;
  const headers = new Headers();

  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("accept", req.headers.get("accept") ?? "application/json");

  let usedToken: string | null = null;
  if (authMode !== "none") {
    usedToken = tokenOverride ?? session?.token ?? null;
    if (usedToken) headers.set("authorization", `Bearer ${usedToken}`);
  }

  const method = req.method.toUpperCase();
  let body: ArrayBuffer | undefined;
  let bodyPreview: unknown;
  if (method !== "GET" && method !== "HEAD") {
    body = await req.arrayBuffer();
    bodyPreview = previewBody(contentType, body);
  }

  const started = Date.now();
  let res: Response;
  try {
    res = await fetch(target, { method, headers, body, cache: "no-store" });
  } catch (err) {
    const durationMs = Date.now() - started;
    publish("http", `${method} ${target} -- unreachable`, {
      level: "error",
      durationMs,
      detail: { error: (err as Error).message },
    });
    return NextResponse.json(
      { __consoleError: "backend unreachable", target, message: (err as Error).message },
      { status: 502 },
    );
  }

  const durationMs = Date.now() - started;
  const resContentType = res.headers.get("content-type") ?? "";
  const raw = await res.text();
  let parsed: unknown = raw;
  if (resContentType.includes("application/json")) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = raw;
    }
  }

  publish("http", `${method} /${path.join("/")}${url.search} -> ${res.status}`, {
    level: res.ok ? "info" : res.status >= 500 ? "error" : "warn",
    durationMs,
    detail: {
      target,
      status: res.status,
      auth: authMode === "none" ? "none" : usedToken ? `bearer ${usedToken.slice(0, 18)}...` : "none (no session)",
      requestBody: trim(bodyPreview),
      responseBody: trim(parsed),
    },
  });

  return NextResponse.json(
    {
      status: res.status,
      ok: res.ok,
      durationMs,
      contentType: resContentType,
      body: parsed,
      target,
    },
    { status: 200 },
  );
}

function previewBody(contentType: string | null, body: ArrayBuffer): unknown {
  const text = Buffer.from(body).toString("utf8");
  if (contentType?.includes("application/json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  if (contentType?.includes("multipart/form-data")) {
    // keep the readable field lines, drop binary payloads
    return text
      .split(/\r?\n/)
      .filter((l) => l.startsWith("Content-Disposition") || (l.length > 0 && l.length < 300 && !/[\x00-\x08]/.test(l)))
      .slice(0, 40)
      .join("\n");
  }
  return text.length > 2000 ? `${text.slice(0, 2000)}...` : text;
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
