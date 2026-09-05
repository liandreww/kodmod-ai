"""
KODMOD AI — Streaming Chat WebSocket (`/ws/chat`)
=================================================

Text in, text out. Speech recognition and synthesis both live in the browser,
so this socket carries JSON only and never a byte of audio.

Client sends::

    {"type": "message", "text": "...", "subject_id": "...|null",
     "session_id": "...|null"}
    {"type": "ping"}

Server sends, in order, per turn::

    {"type": "session", "session_id": "..."}   once, so the client can resume
    {"type": "state",   "node": "..."}         which node is running
    {"type": "token",   "text": "..."}         repeatedly, as the tutor writes
    {"type": "final",   "text": ..., "intent": ..., "sources": [...], "quiz_progress": ...}
    {"type": "error",   "message": "..."}      instead of `final`, on failure

Tokens are a live preview. The `final` text is the authoritative answer: it has
been through the accessibility node, which rewrites visual references and
splits long sentences, so it is not merely the concatenated tokens. Clients
should render the streamed tokens and then replace them with `final`.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.chat_service import (
    build_turn_state,
    log_turn,
    open_session,
    reply_text,
    sources,
    update_session_mode,
)
from api.dependencies import authenticate_ws
from graphs.main_graph import run_turn

log = logging.getLogger(__name__)
router = APIRouter()

MAX_TEXT_CHARS = 4000

# Nodes worth telling the client about. The rest are too fast to be worth a
# frame, and naming every one would turn a progress hint into noise.
_PROGRESS_NODES = frozenset(
    {"intent_router", "rag_retrieval", "tutoring", "problem_generator", "quiz_ask", "scoring"}
)

# Every node in the graph, so their partial returns can be merged into the
# turn's result. Kept in sync with `graphs/main_graph.build_kodmod_graph`.
_GRAPH_NODES = frozenset(
    {
        "intent_router",
        "rag_retrieval",
        "tutoring",
        "mini_quiz",
        "problem_generator",
        "quiz_ask",
        "scoring",
        "quiz_analyzer",
        "update_student_model",
        "analytics",
        "recommendation",
        "accessibility",
        "reflection",
    }
)


def _as_uuid(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


@router.websocket("/chat")  # mounted under /ws
async def chat_ws(websocket: WebSocket) -> None:
    student = await authenticate_ws(websocket)  # closes with 1008 on failure
    await websocket.accept()
    log.info("Chat socket open for %s", student.username)

    try:
        while True:
            frame = await websocket.receive_json()

            if frame.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if frame.get("type") != "message":
                await websocket.send_json({"type": "error", "message": "Unknown frame type."})
                continue

            text = str(frame.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "Message was empty."})
                continue
            if len(text) > MAX_TEXT_CHARS:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Message is longer than {MAX_TEXT_CHARS} characters.",
                    }
                )
                continue

            await _run_one_turn(
                websocket,
                student,
                text=text,
                session_id=_as_uuid(frame.get("session_id")),
                subject_id=_as_uuid(frame.get("subject_id")),
            )

    except WebSocketDisconnect:
        log.info("Chat socket closed for %s", student.username)
    except Exception:
        log.exception("Chat socket failed for %s", student.username)
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass  # already closed


async def _run_one_turn(
    websocket: WebSocket,
    student,
    *,
    text: str,
    session_id: uuid.UUID | None,
    subject_id: uuid.UUID | None,
) -> None:
    started = time.perf_counter()

    resolved_id = await open_session(
        student_id=student.id,
        session_id=session_id,
        subject_id=subject_id,
        first_text=text,
    )
    await websocket.send_json({"type": "session", "session_id": str(resolved_id)})

    state = await build_turn_state(
        student=student, session_id=resolved_id, text=text, subject_id=subject_id
    )
    graph = websocket.app.state.graph
    config = {"configurable": {"thread_id": str(resolved_id)}}

    # Accumulate each node's partial return rather than trusting one root
    # event: node names are ours, the root chain's name is LangGraph's to change.
    final: dict = {}
    try:
        async for event in run_turn(graph, state, config):
            kind = event.get("event")
            name = event.get("name")
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if token := getattr(chunk, "content", ""):
                    await websocket.send_json({"type": "token", "text": token})
            elif kind == "on_chain_start" and name in _PROGRESS_NODES:
                await websocket.send_json({"type": "state", "node": name})
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and (name in _GRAPH_NODES or name == "LangGraph"):
                    final.update(output)
    except Exception:
        log.exception("Turn failed for session %s", resolved_id)
        await websocket.send_json(
            {
                "type": "error",
                "message": "Maaf, terjadi kesalahan saat menyiapkan jawaban. Coba lagi.",
            }
        )
        return

    answer = reply_text(final)
    latency_ms = int((time.perf_counter() - started) * 1000)

    await log_turn(resolved_id, role="student", text=text, intent=final.get("intent"))
    await log_turn(
        resolved_id,
        role="assistant",
        text=answer,
        intent=final.get("intent"),
        latency_ms=latency_ms,
    )
    await update_session_mode(resolved_id, final.get("intent"))

    quiz_progress = (
        {
            "index": final.get("current_question_index", 0),
            "total": len(final.get("quiz_questions") or []),
        }
        if final.get("intent") == "quiz" and final.get("quiz_questions")
        else None
    )

    await websocket.send_json(
        {
            "type": "final",
            "session_id": str(resolved_id),
            "text": answer,
            "intent": str(final.get("intent") or "unknown"),
            "next_action": str(final.get("next_action") or "end"),
            "sources": sources(final),
            "latency_ms": latency_ms,
            "quiz_progress": quiz_progress,
        }
    )
