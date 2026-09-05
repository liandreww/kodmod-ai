import { requireCaller, requireOpenAIKey } from "@/lib/server-auth";

/**
 * Speech to text.
 *
 * The browser records audio and posts the blob here; this route calls OpenAI
 * and returns plain text. The API key never reaches the browser, which is the
 * whole reason this route exists rather than calling OpenAI from the client.
 */

export const runtime = "nodejs";
export const maxDuration = 60;

const MAX_BYTES = 25 * 1024 * 1024; // OpenAI's own upload ceiling.

export async function POST(request: Request) {
  const denied = await requireCaller(request);
  if (denied) return denied;

  const keyOrError = requireOpenAIKey();
  if (keyOrError instanceof Response) return keyOrError;

  let audio: File | null = null;
  let language = "id";
  try {
    const form = await request.formData();
    const file = form.get("audio");
    if (file instanceof File) audio = file;
    const lang = form.get("language");
    if (typeof lang === "string" && lang) language = lang;
  } catch {
    return Response.json({ error: "Permintaan tidak valid." }, { status: 400 });
  }

  if (!audio || audio.size === 0) {
    return Response.json({ error: "Tidak ada audio yang dikirim." }, { status: 400 });
  }
  if (audio.size > MAX_BYTES) {
    return Response.json({ error: "Rekaman terlalu panjang." }, { status: 413 });
  }

  const payload = new FormData();
  payload.append("file", audio, audio.name || "rekaman.webm");
  payload.append("model", process.env.OPENAI_TRANSCRIBE_MODEL ?? "gpt-4o-transcribe");
  payload.append("language", language);
  payload.append("response_format", "text");

  const response = await fetch("https://api.openai.com/v1/audio/transcriptions", {
    method: "POST",
    headers: { Authorization: `Bearer ${keyOrError.key}` },
    body: payload,
  });

  const body = await response.text();
  if (!response.ok) {
    console.error("transcription failed", response.status, body);
    return Response.json({ error: "Transkripsi gagal. Coba lagi." }, { status: 502 });
  }

  return Response.json({ text: body.trim() });
}
