import { NextRequest } from "next/server";
import { recent, subscribe, type ActivityEvent } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Server-sent stream of the unified activity timeline. */
export async function GET(req: NextRequest) {
  const after = Number(req.nextUrl.searchParams.get("after") ?? 0);
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    start(controller) {
      let closed = false;
      const send = (ev: ActivityEvent) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(ev)}\n\n`));
        } catch {
          closed = true;
        }
      };

      for (const ev of recent(after, 500)) send(ev);

      const unsubscribe = subscribe(send);
      const keepAlive = setInterval(() => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(": ping\n\n"));
        } catch {
          closed = true;
        }
      }, 20_000);

      req.signal.addEventListener("abort", () => {
        closed = true;
        clearInterval(keepAlive);
        unsubscribe();
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      });
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
