"""
KODMOD AI — Voice WebSocket
============================

Bidirectional streaming endpoint. Client opens a single WS, sends audio
frames (16 kHz mono PCM) or a text control frame, and receives JSON frames:

* ``{"type": "partial_transcript", "text": ...}`` — interim STT output
* ``{"type": "token", "text": ...}`` — streamed LLM tokens for the turn
* ``{"type": "audio_uri", "uri": ...}`` — path to synthesized TTS audio
  (empty string when ``TTS_ENABLED`` is false); raw audio bytes are also sent
  as binary frames while a TTS backend is enabled
* ``{"type": "final", "session_id": ...}`` — the turn completed

Text mode
---------
When ``STT_ENABLED`` is false the client drives a turn purely with text:
``{"event": "end_of_speech", "transcript": "<student utterance>"}``. The
``transcript`` field is used directly as the STT result and ``StreamingSTT`` is
never constructed.

Authentication
--------------
The WS upgrade requires a JWT, read from the ``?token=`` query param (an
``Authorization: Bearer`` header is accepted as a fallback). See
``api/dependencies.authenticate_ws``.

Rate limiting
-------------
Per-student rate limit enforced via Redis token bucket — see
`api/middleware/rate_limit.py`.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.dependencies import authenticate_ws
from config.settings import settings
from graphs.main_graph import run_turn
from graphs.state import build_learning_profile, initial_state
from voice.streaming import StreamingSTT, stream_tts

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/voice")
async def voice_ws(websocket: WebSocket):
    student = await authenticate_ws(websocket)
    if not student:  # pragma: no cover - authenticate_ws raises on failure
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    log.info("WS opened for student=%s", student.id)

    session_id = str(uuid4())
    lang = student.preferred_language or "id"
    stt = StreamingSTT(language=lang) if settings.STT_ENABLED else None

    async def _handle_event(event: dict) -> None:
        kind = event["event"]
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            delta = chunk.content if hasattr(chunk, "content") else ""
            await websocket.send_json({"type": "token", "text": delta})
        elif kind == "on_chain_end" and event.get("name") == "accessibility":
            # Stream TTS audio as soon as the accessibility node completes.
            if settings.TTS_ENABLED:
                final_text = event["data"]["output"].get("accessible_response", "")
                try:
                    async for frame in stream_tts(final_text):
                        await websocket.send_bytes(frame)
                except Exception:  # pragma: no cover - TTS backend is best-effort
                    log.exception("stream_tts failed")
        elif kind == "on_chain_end" and event.get("name") == "tts":
            audio_uri = event["data"]["output"].get("audio_response_path", "")
            await websocket.send_json({"type": "audio_uri", "uri": audio_uri})

    try:
        while True:
            # ---- Phase 1: collect audio chunks until end-of-utterance -----
            transcript = await _collect_utterance(websocket, stt)
            if transcript is None:
                continue  # client sent metadata or an empty frame
            log.info("Final transcript: %s", transcript[:80])

            # ---- Phase 2: drive LangGraph for one turn -------------------
            state = initial_state(
                session_id=session_id,
                student_id=str(student.id),
                audio_input_path="",  # we already transcribed
            )
            state["transcribed_text"] = transcript
            state["user_input"] = transcript
            state["learning_profile"] = build_learning_profile(student)

            graph = websocket.app.state.graph
            config = {"configurable": {"thread_id": session_id}}

            async for event in run_turn(graph, state, config):
                await _handle_event(event)

            # The graph is compiled with interrupt_after=["reflection"] when a
            # checkpointer is present; resume it so accessibility + tts run.
            for _ in range(4):
                try:
                    snapshot = await graph.aget_state(config)
                except Exception:  # pragma: no cover - no checkpointer configured
                    break
                if not snapshot.next:
                    break
                async for event in run_turn(graph, None, config):
                    await _handle_event(event)
            else:
                log.error("WS turn left graph interrupted: session=%s", session_id)

            await websocket.send_json({"type": "final", "session_id": session_id})

    except WebSocketDisconnect:
        log.info("WS closed for student=%s", student.id)
    except Exception:
        log.exception("WS handler crashed")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


# ---------------------------------------------------------------------------
# Audio collection
# ---------------------------------------------------------------------------


async def _collect_utterance(ws: WebSocket, stt: StreamingSTT | None) -> str | None:
    """
    Receive frames until the utterance ends, then return its transcript.

    * Binary frames are PCM audio: fed to ``StreamingSTT`` (when enabled) after a
      per-frame size check; partial transcripts are forwarded to the client.
    * A ``{"event": "end_of_speech"}`` text frame ends the utterance; an optional
      ``transcript`` field is used verbatim (text mode).
    * Non-JSON text frames and unknown control events are ignored.
    """
    transcript = ""
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(code=msg.get("code", status.WS_1000_NORMAL_CLOSURE))

        data = msg.get("bytes")
        if data is not None:
            if len(data) > settings.WS_MAX_FRAME_BYTES:
                log.warning("WS inbound frame too large: %d bytes", len(data))
                await ws.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                raise WebSocketDisconnect(code=status.WS_1009_MESSAGE_TOO_BIG)
            if stt is None:
                continue  # text mode — ignore audio
            result = await stt.feed(data)
            partial = result.get("partial")
            final = result.get("final")
            if partial:
                transcript = partial
                await ws.send_json({"type": "partial_transcript", "text": partial})
            if final:
                return final
            continue

        text = msg.get("text")
        if text is not None:
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue  # not JSON — ignore
            if not isinstance(payload, dict):
                continue
            if payload.get("event") == "end_of_speech":
                supplied = payload.get("transcript")
                if isinstance(supplied, str) and supplied.strip():
                    return supplied
                if stt is not None:
                    flushed = await stt.flush_segment()
                    if flushed:
                        return flushed
                return transcript or ""
            # any other control event is ignored
