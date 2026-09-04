"use client";


import { useCallback, useEffect, useRef, useState } from "react";
import { Card, Empty, ErrorNote, Json, Spinner, StatusBadge, StatusDot } from "@/components/ui";
import { callApi, callConsole, fmtMs, logWs } from "@/lib/client";
import { EffectsRail } from "@/components/EffectsRail";

type Transport = "rest" | "ws";

interface Turn {
  role: "student" | "tutor";
  text: string;
  meta?: Record<string, unknown>;
  status?: number;
  durationMs?: number;
}

const SAMPLE_UTTERANCES = [
  "jelaskan apa itu pecahan",
  "bagaimana cara menjumlahkan pecahan berbeda penyebut",
  "apa itu pecahan senilai",
  "beri aku contoh soal pecahan",
  "ulangi penjelasan tadi",
  "lebih pelan",
  "berhenti",
  "bantuan",
];

export default function TutorPage() {
  const [transport, setTransport] = useState<Transport>("rest");
  const [text, setText] = useState("jelaskan apa itu pecahan");
  const [sessionId, setSessionId] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRaw, setLastRaw] = useState<unknown>(null);

  // WebSocket state
  const wsRef = useRef<WebSocket | null>(null);
  const [wsState, setWsState] = useState<"closed" | "connecting" | "open" | "error">("closed");
  const [wsCloseInfo, setWsCloseInfo] = useState<string>("");
  const [streamText, setStreamText] = useState("");
  const [wsFrames, setWsFrames] = useState<{ type: string; text?: string; note?: string }[]>([]);
  const [audioChunks, setAudioChunks] = useState<Blob[]>([]);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  useEffect(() => () => wsRef.current?.close(), []);

  /* ---------------------------------------------------------------- REST */

  const sendRest = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setTurns((t) => [...t, { role: "student", text }]);

    const res = await callApi<Record<string, unknown>>("voice/text", {
      method: "POST",
      form: { text, session_id: sessionId || undefined },
    });
    setLastRaw(res);

    if (res.ok && res.body && typeof res.body === "object") {
      const body = res.body as Record<string, unknown>;
      if (body.session_id) setSessionId(String(body.session_id));
      setTurns((t) => [
        ...t,
        {
          role: "tutor",
          text: String(body.response_text ?? ""),
          meta: body,
          status: res.status,
          durationMs: res.durationMs,
        },
      ]);
    } else {
      setError(`POST /voice/text -> ${res.status}`);
      setTurns((t) => [
        ...t,
        { role: "tutor", text: "", meta: res.body as Record<string, unknown>, status: res.status, durationMs: res.durationMs },
      ]);
    }
    setText("");
    setBusy(false);
  };

  /* ------------------------------------------------------------------ WS */

  const connectWs = useCallback(async () => {
    setError(null);
    setWsCloseInfo("");
    const info = await callConsole<{
      session: { token: string } | null;
      profile: { wsUrl: string };
    }>("/api/session");

    if (!info.session?.token) {
      setError("Sign in first — /ws/voice closes with 1008 before accept when the token is missing.");
      return;
    }

    const url = `${info.profile.wsUrl}/ws/voice?token=${encodeURIComponent(info.session.token)}`;
    setWsState("connecting");
    logWs("out", `connect ${info.profile.wsUrl}/ws/voice`, { tokenPrefix: info.session.token.slice(0, 18) });

    const ws = new WebSocket(url);
    ws.binaryType = "blob";
    wsRef.current = ws;

    ws.onopen = () => {
      setWsState("open");
      setWsFrames([]);
      logWs("info", "websocket open");
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        setAudioChunks((c) => [...c, ev.data as Blob]);
        logWs("in", `binary TTS frame (${(ev.data as Blob).size} bytes)`);
        setWsFrames((f) => {
          const last = f[f.length - 1];
          if (last?.type === "binary") {
            const copy = f.slice(0, -1);
            const n = Number(last.note?.match(/\d+/)?.[0] ?? 1) + 1;
            return [...copy, { type: "binary", note: `${n} audio frames` }];
          }
          return [...f, { type: "binary", note: "1 audio frames" }];
        });
        return;
      }

      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        logWs("in", `non-JSON text frame: ${ev.data.slice(0, 120)}`, undefined, "warn");
        return;
      }
      logWs("in", `${msg.type}${msg.text ? `: ${String(msg.text).slice(0, 80)}` : ""}`, msg);
      setWsFrames((f) => [...f, { type: String(msg.type), text: msg.text ? String(msg.text) : undefined }]);

      if (msg.type === "token") setStreamText((s) => s + String(msg.text ?? ""));
      else if (msg.type === "partial_transcript") {
        /* interim STT; nothing to accumulate in text mode */
      } else if (msg.type === "audio_uri") {
        setTurns((t) => {
          const copy = [...t];
          const last = copy[copy.length - 1];
          if (last?.role === "tutor") last.meta = { ...(last.meta ?? {}), audio_uri: msg.uri };
          return copy;
        });
      } else if (msg.type === "final") {
        setSessionId(String(msg.session_id ?? ""));
        setStreamText((s) => {
          if (s.trim()) setTurns((t) => [...t, { role: "tutor", text: s, meta: { via: "ws", session_id: msg.session_id } }]);
          return "";
        });
        setBusy(false);
      }
    };

    ws.onerror = () => {
      setWsState("error");
      logWs("info", "websocket error", undefined, "error");
    };

    ws.onclose = (e) => {
      setWsState("closed");
      setBusy(false);
      const reason =
        e.code === 1008
          ? "1008 policy violation — bad/expired token, wrong role, or unknown student (auth runs before accept)"
          : e.code === 1009
            ? "1009 message too big"
            : e.code === 1011
              ? "1011 internal error"
              : `${e.code}${e.reason ? ` ${e.reason}` : ""}`;
      setWsCloseInfo(reason);
      logWs("info", `websocket closed: ${reason}`, undefined, e.code === 1000 ? "info" : "warn");
    };
  }, []);

  const sendWs = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim()) return;
    const frame = { event: "end_of_speech", transcript: text };
    setTurns((t) => [...t, { role: "student", text }]);
    setStreamText("");
    setAudioChunks([]);
    setAudioUrl(null);
    setBusy(true);
    ws.send(JSON.stringify(frame));
    logWs("out", `end_of_speech: ${text}`, frame);
    setText("");
  };

  const buildAudio = () => {
    if (!audioChunks.length) return;
    const blob = new Blob(audioChunks);
    setAudioUrl(URL.createObjectURL(blob));
  };

  const send = () => (transport === "rest" ? sendRest() : sendWs());

  return (
    <>
      <div className="d-flex align-items-center justify-content-between mb-3">
        <h5 className="mb-0">Tutor</h5>
        <div className="btn-group btn-group-sm">
          <button
            type="button"
            className={`btn ${transport === "rest" ? "btn-primary" : "btn-outline-secondary"}`}
            onClick={() => setTransport("rest")}
            title="POST /voice/text (multipart form)"
          >
            <i className="bi bi-arrow-left-right me-1" aria-hidden="true" />
            REST
          </button>
          <button
            type="button"
            className={`btn ${transport === "ws" ? "btn-primary" : "btn-outline-secondary"}`}
            onClick={() => setTransport("ws")}
            title="WS /ws/voice with an end_of_speech transcript frame"
          >
            <i className="bi bi-broadcast me-1" aria-hidden="true" />
            WebSocket
          </button>
        </div>
      </div>

      <ErrorNote error={error} />

      <div className="split">
        <div>
          <Card
            title="Conversation"
            icon="bi-chat-left-text"
            actions={
              <>
                {transport === "ws" && (
                  <span className="d-flex align-items-center gap-2 small">
                    <StatusDot state={wsState === "open" ? "ok" : wsState === "connecting" ? "warn" : "bad"} />
                    {wsState}
                    {wsState === "open" ? (
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-danger"
                        onClick={() => wsRef.current?.close()}
                      >
                        Disconnect
                      </button>
                    ) : (
                      <button type="button" className="btn btn-sm btn-outline-primary" onClick={connectWs}>
                        Connect
                      </button>
                    )}
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn-sm btn-outline-secondary"
                  onClick={() => {
                    setTurns([]);
                    setStreamText("");
                    setLastRaw(null);
                  }}
                  title="Clear the transcript view"
                >
                  <i className="bi bi-eraser" aria-hidden="true" />
                </button>
              </>
            }
          >
            {wsCloseInfo && transport === "ws" && (
              <div className="alert alert-warning py-1 px-2 small mono">{wsCloseInfo}</div>
            )}

            <div className="chat-scroll d-flex flex-column gap-2 mb-3">
              {turns.length === 0 && !streamText && <Empty icon="bi-chat-dots">No turns yet</Empty>}
              {turns.map((t, i) => (
                <div key={i} className={`bubble ${t.role}`}>
                  <div className="d-flex align-items-center gap-2 mb-1">
                    <span className="badge bg-secondary">{t.role}</span>
                    <StatusBadge status={t.status} />
                    {t.durationMs !== undefined && (
                      <span className="small text-secondary">{fmtMs(t.durationMs)}</span>
                    )}
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{t.text || <em className="text-secondary">empty</em>}</div>
                  {t.meta && (
                    <details className="mt-2">
                      <summary className="small text-secondary">response payload</summary>
                      <Json value={t.meta} />
                    </details>
                  )}
                </div>
              ))}
              {streamText && (
                <div className="bubble tutor">
                  <div className="d-flex align-items-center gap-2 mb-1">
                    <span className="badge bg-info text-dark">streaming</span>
                    <Spinner show />
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{streamText}</div>
                </div>
              )}
            </div>

            <div className="d-flex flex-wrap gap-1 mb-2">
              {SAMPLE_UTTERANCES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="btn btn-sm btn-outline-secondary py-0"
                  onClick={() => setText(s)}
                >
                  {s}
                </button>
              ))}
            </div>

            <div className="input-group">
              <input
                className="form-control"
                value={text}
                placeholder="Utterance text"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <button
                type="button"
                className="btn btn-primary"
                onClick={send}
                disabled={busy || !text.trim() || (transport === "ws" && wsState !== "open")}
              >
                <i className="bi bi-send me-1" aria-hidden="true" />
                Send
                <span className="ms-2">
                  <Spinner show={busy} />
                </span>
              </button>
            </div>
          </Card>

          {transport === "ws" && (
            <Card
              title="Frames"
              icon="bi-list-ol"
              actions={
                audioChunks.length > 0 ? (
                  <button type="button" className="btn btn-sm btn-outline-primary" onClick={buildAudio}>
                    <i className="bi bi-play-circle me-1" aria-hidden="true" />
                    Assemble {audioChunks.length} audio frames
                  </button>
                ) : null
              }
            >
              {audioUrl && <audio className="w-100 mb-2" controls src={audioUrl} />}
              {wsFrames.length === 0 ? (
                <Empty icon="bi-broadcast">No frames received</Empty>
              ) : (
                <div className="log-list border rounded" style={{ maxHeight: 220 }}>
                  {wsFrames.map((f, i) => (
                    <div key={i} className="px-2 py-1 border-bottom">
                      <span className="badge bg-secondary me-2">{f.type}</span>
                      <span>{f.text ?? f.note}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {lastRaw != null && transport === "rest" && (
            <Card title="Last proxy response" icon="bi-code-square">
              <Json value={lastRaw} />
            </Card>
          )}
        </div>

        <EffectsRail sessionId={sessionId} onSessionChange={setSessionId} />
      </div>
    </>
  );
}

