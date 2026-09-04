import { NextRequest, NextResponse } from "next/server";
import { publish, trim } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * The WebSocket runs in the browser (it is the one thing that cannot be proxied
 * server-side), so the page posts each frame here to keep the activity timeline
 * complete.
 */
export async function POST(req: NextRequest) {
  const { direction, label, detail, level } = await req.json();
  const arrow = direction === "in" ? "<-" : direction === "out" ? "->" : "--";
  publish("ws", `${arrow} ${label}`, { level: level ?? "info", detail: trim(detail) });
  return NextResponse.json({ ok: true });
}
