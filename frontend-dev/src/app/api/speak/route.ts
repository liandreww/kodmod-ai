import { requireCaller, requireOpenAIKey } from "@/lib/server-auth";

/**
 * Text to speech.
 *
 * Called once per sentence rather than once per answer, so playback can start
 * while the rest of the reply is still being written. Returns raw audio that
 * the client hands straight to an <audio> element.
 */

export const runtime = "nodejs";
export const maxDuration = 60;

const MAX_CHARS = 2000;

export async function POST(request: Request) {
  const denied = await requireCaller(request);
  if (denied) return denied;

  const keyOrError = requireOpenAIKey();
  if (keyOrError instanceof Response) return keyOrError;

  let text = "";
  try {
    const body = (await request.json()) as { text?: unknown };
    if (typeof body.text === "string") text = body.text.trim();
  } catch {
    return Response.json({ error: "Permintaan tidak valid." }, { status: 400 });
  }

  if (!text) {
    return Response.json({ error: "Tidak ada teks untuk dibacakan." }, { status: 400 });
  }
  if (text.length > MAX_CHARS) text = text.slice(0, MAX_CHARS);

  const response = await fetch("https://api.openai.com/v1/audio/speech", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${keyOrError.key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.OPENAI_TTS_MODEL ?? "gpt-4o-mini-tts-2025-12-15",
      voice: process.env.OPENAI_TTS_VOICE ?? "alloy",
      input: text,
      response_format: "mp3",
    }),
  });

  if (!response.ok) {
    console.error("speech failed", response.status, await response.text());
    return Response.json({ error: "Pembacaan gagal." }, { status: 502 });
  }

  return new Response(response.body, {
    headers: {
      "Content-Type": "audio/mpeg",
      "Cache-Control": "no-store",
    },
  });
}
