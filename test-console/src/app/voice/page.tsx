"use client";

import { useState } from "react";
import { Card, Empty, ErrorNote, Field, Json, Spinner, StatusBadge } from "@/components/ui";
import { EffectsRail } from "@/components/EffectsRail";
import { callApi, fmtMs } from "@/lib/client";

/** 16 kHz mono 16-bit PCM WAV, matching what the STT layer expects. */
function makeWav(seconds: number, frequency: number): Blob {
  const sampleRate = 16_000;
  const samples = Math.floor(sampleRate * seconds);
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);

  const writeString = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples * 2, true);

  for (let i = 0; i < samples; i++) {
    const value = frequency === 0 ? 0 : Math.round(Math.sin((2 * Math.PI * frequency * i) / sampleRate) * 8000);
    view.setInt16(44 + i * 2, value, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export default function VoicePage() {
  const [file, setFile] = useState<File | Blob | null>(null);
  const [fileName, setFileName] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [meta, setMeta] = useState<{ status: number; durationMs: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState<unknown>(null);
  const [forceBadType, setForceBadType] = useState(false);

  const pickGenerated = (seconds: number, frequency: number, label: string) => {
    setFile(makeWav(seconds, frequency));
    setFileName(label);
    setError(null);
  };

  const send = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);

    const payload = forceBadType
      ? new Blob([await file.arrayBuffer()], { type: "text/plain" })
      : file;

    const res = await callApi<Record<string, unknown>>("voice/chat", {
      method: "POST",
      form: {
        audio: new File([payload], fileName || "audio.wav", { type: payload.type }),
        session_id: sessionId || undefined,
      },
    });
    setRaw(res);
    setMeta({ status: res.status, durationMs: res.durationMs });

    if (res.ok) {
      const body = res.body as Record<string, unknown>;
      setResult(body);
      if (body.session_id) setSessionId(String(body.session_id));
    } else {
      setResult(null);
      setError(
        `POST /voice/chat -> ${res.status}` +
          (res.status === 400 ? " (content_type must start with audio/, and the body must not be empty)" : ""),
      );
    }
    setBusy(false);
  };

  return (
    <>
      <h5 className="mb-3">Audio upload</h5>
      <div className="alert alert-secondary py-1 px-2 small">
        <code>POST /voice/chat</code> is multipart. With <code>STT_ENABLED=false</code> (the test profile default) the
        transcript comes back empty and the graph runs on an empty utterance — use the Tutor page for real turns.
      </div>
      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card title="Request" icon="bi-file-earmark-music">
            <Field label="audio file" hint="wav / mp3 / ogg, max ~7.7 MB">
              <input
                type="file"
                className="form-control form-control-sm"
                accept="audio/*"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setFile(f);
                    setFileName(f.name);
                  }
                }}
              />
            </Field>

            <div className="d-flex flex-wrap gap-2 my-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={() => pickGenerated(1, 0, "silence-1s.wav")}
              >
                <i className="bi bi-soundwave me-1" aria-hidden="true" />
                1s silence
              </button>
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={() => pickGenerated(2, 440, "tone-440hz-2s.wav")}
              >
                <i className="bi bi-soundwave me-1" aria-hidden="true" />
                2s tone
              </button>
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={() => {
                  setFile(new Blob([], { type: "audio/wav" }));
                  setFileName("empty.wav");
                }}
                title="Expects 400 empty audio file"
              >
                <i className="bi bi-exclamation-circle me-1" aria-hidden="true" />
                Empty body
                <span className="badge bg-secondary ms-1">400</span>
              </button>
            </div>

            <div className="form-check form-switch mb-3">
              <input
                className="form-check-input"
                type="checkbox"
                id="badtype"
                checked={forceBadType}
                onChange={(e) => setForceBadType(e.target.checked)}
              />
              <label className="form-check-label small" htmlFor="badtype">
                Send as text/plain <span className="badge bg-secondary">expects 400</span>
              </label>
            </div>

            <Field label="session_id" hint="optional">
              <input
                className="form-control form-control-sm mono"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
              />
            </Field>

            <div className="d-flex align-items-center gap-2 mt-3">
              <button type="button" className="btn btn-sm btn-primary" onClick={send} disabled={busy || !file}>
                <i className="bi bi-upload me-1" aria-hidden="true" />
                Upload
              </button>
              <Spinner show={busy} />
              {fileName && (
                <span className="small text-secondary mono">
                  {fileName} · {file ? `${(file.size / 1024).toFixed(1)} KB` : ""}
                </span>
              )}
            </div>
          </Card>

          <Card
            title="Response"
            icon="bi-reply"
            actions={
              <>
                <StatusBadge status={meta?.status} />
                <span className="small text-secondary">{fmtMs(meta?.durationMs)}</span>
              </>
            }
          >
            {!result ? (
              <Empty icon="bi-reply">Nothing yet</Empty>
            ) : (
              <>
                <table className="table table-sm mono mb-3">
                  <tbody>
                    {["session_id", "transcript", "intent", "next_action", "audio_uri"].map((k) => (
                      <tr key={k}>
                        <td className="text-secondary" style={{ width: 130 }}>
                          {k}
                        </td>
                        <td className="text-break">{String(result[k] ?? "-")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="small fw-semibold mb-1">response_text</div>
                <div style={{ whiteSpace: "pre-wrap" }}>{String(result.response_text ?? "")}</div>
              </>
            )}
          </Card>

          {raw != null && (
            <Card title="Raw proxy response" icon="bi-code-square">
              <Json value={raw} />
            </Card>
          )}
        </div>

        <EffectsRail sessionId={sessionId} onSessionChange={setSessionId} />
      </div>
    </>
  );
}
