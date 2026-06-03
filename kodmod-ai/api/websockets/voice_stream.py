"""
KODMOD AI — Voice WebSocket
============================

Bidirectional streaming endpoint. Client opens a single WS, sends audio
frames (16 kHz mono PCM or Opus), and receives:

* `transcript` events as soon as STT produces partial transcriptions
* `agent_event` events forwarded from LangGraph's `astream_events`
* `audio_chunk` events containing TTS-synthesized audio bytes (sent as
  binary frames so the client can play them incrementally)
* `final` event when the turn completes

Authentication
--------------
The WS upgrade requires a JWT in the `Authorization` header (or `?token=`
fallback for browsers that can't set headers on WebSocket).

Rate limiting
-------------
Per-student rate limit enforced via Redis token bucket — see
`api/middleware/rate_limit.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.dependencies import authenticate_ws
from graphs.main_graph import run_turn
from graphs.state import initial_state
from voice.streaming import StreamingSTT, stream_tts

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/voice")
async def voice_ws(websocket: WebSocket):
    student = await authenticate_ws(websocket)
    if not student:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    log.info("WS opened for student=%s", student.id)

    session_id = str(uuid4())
    stt = StreamingSTT(language=student.language or "id")

    try:
        while True:
            # ---- Phase 1: collect audio chunks until end-of-utterance -----
            transcript = await _collect_utterance(websocket, stt)
            if transcript is None:
                continue  # client sent metadata or empty frame
            log.info("Final transcript: %s", transcript[:80])

            # ---- Phase 2: drive LangGraph for one turn -------------------
            state = initial_state(
                session_id=session_id,
                student_id=student.id,
                audio_input_path="",  # we already transcribed
            )
            state["transcribed_text"] = transcript
            state["user_input"] = transcript
            state["learning_profile"] = student.profile

            graph = websocket.app.state.graph
            config = {"configurable": {"thread_id": session_id}}

            assembled_text = []
            async for event in run_turn(graph, state, config):
                kind = event["event"]

                if kind == "on_chat_model_stream":
                    delta = event["data"]["chunk"].content if hasattr(
                        event["data"]["chunk"], "content"
                    ) else ""
                    assembled_text.append(delta)
                    await websocket.send_json({
                        "type": "token",
                        "text": delta,
                    })

                elif kind == "on_chain_end" and event["name"] == "accessibility":
                    # Start streaming TTS as soon as accessibility node completes
                    final_text = event["data"]["output"].get("accessible_response", "")
                    await stream_tts(websocket, final_text)

                elif kind == "on_chain_end" and event["name"] == "tts":
                    audio_uri = event["data"]["output"].get("audio_response_path", "")
                    await websocket.send_json({"type": "audio_uri", "uri": audio_uri})

            await websocket.send_json({"type": "final", "session_id": session_id})

    except WebSocketDisconnect:
        log.info("WS closed for student=%s", student.id)
    except Exception:
        log.exception("WS handler crashed")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


# ---------------------------------------------------------------------------
# Audio collection
# ---------------------------------------------------------------------------

async def _collect_utterance(ws: WebSocket, stt: StreamingSTT) -> str | None:
    """
    Receive audio frames until VAD says the user stopped talking, then return
    the final transcript. Sends partial transcripts back to the client.
    """
    transcript = ""
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return None
        if "bytes" in msg and msg["bytes"]:
            partial, is_final = await stt.feed(msg["bytes"])
            if partial:
                transcript = partial
                await ws.send_json({"type": "partial_transcript", "text": partial})
            if is_final:
                return transcript
        elif "text" in msg and msg["text"]:
            data = json.loads(msg["text"])
            if data.get("event") == "end_of_speech":
                return transcript or ""
