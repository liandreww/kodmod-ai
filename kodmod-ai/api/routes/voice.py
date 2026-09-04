"""
KODMOD AI — Voice REST Routes
==============================

Non-streaming counterpart to the WebSocket endpoint, useful for:
* Mobile clients that batch full utterances before sending
* Curl / Postman testing
* Asynchronous tutoring (record → upload → poll for response)
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from api.dependencies import current_student
from graphs.state import build_learning_profile, initial_state
from models.student import StudentOut
from voice.streaming import save_upload
from voice.tts import _strip_ssml

log = logging.getLogger(__name__)
router = APIRouter()


def _spoken_text(final_state: dict) -> str:
    """Reading text for a non-streaming client: the accessibility-polished
    response with the TTS-only SSML break markers removed."""
    text = final_state.get("accessible_response") or final_state.get("generated_response") or ""
    return _strip_ssml(text)


async def _drive_to_completion(graph, config: dict, final_state: dict) -> dict:
    """Resume the graph past ``interrupt_after=["reflection"]``.

    When a checkpointer is present the graph is compiled to pause after the
    reflection node, so ``accessibility`` and ``tts`` have not run yet. The
    WebSocket handler does the same drive-to-completion loop; the non-streaming
    REST handlers need it too, otherwise the response falls back to the raw
    (un-polished) ``generated_response``.
    """
    for _ in range(4):
        try:
            snapshot = await graph.aget_state(config)
        except Exception:  # no checkpointer configured (tests) — nothing to resume
            break
        if not getattr(snapshot, "next", ()):
            break
        final_state = await graph.ainvoke(None, config=config)
    return final_state


@router.post("/chat", summary="Single-turn voice chat (upload audio, receive audio).")
async def voice_chat(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str | None = Form(None),
    student: StudentOut = Depends(current_student),
):
    """
    Upload one audio utterance, receive one synthesized response.
    Returns the audio URI plus the full state for debugging.
    """
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="audio file required")

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio file")
    await audio.seek(0)

    sid = session_id or str(uuid4())
    audio_path = await save_upload(audio)

    state = initial_state(
        session_id=sid,
        student_id=str(student.id),
        audio_input_path=str(audio_path),
    )
    state["learning_profile"] = build_learning_profile(student)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": sid}}

    final_state = await graph.ainvoke(state, config=config)
    final_state = await _drive_to_completion(graph, config, final_state)

    log.info(
        "Voice chat turn complete (session=%s, last_node=%s)", sid, final_state.get("last_node")
    )

    return {
        "session_id": sid,
        "transcript": final_state.get("transcribed_text"),
        "intent": final_state.get("intent"),
        "response_text": _spoken_text(final_state),
        "audio_uri": final_state.get("audio_response_path"),
        "next_action": final_state.get("next_action"),
    }


@router.post("/text", summary="Text-in / audio-out (for keyboard fallback).")
async def voice_text(
    request: Request,
    text: str = Form(...),
    session_id: str | None = Form(None),
    student: StudentOut = Depends(current_student),
):
    sid = session_id or str(uuid4())
    state = initial_state(session_id=sid, student_id=str(student.id))
    state["transcribed_text"] = text
    state["user_input"] = text
    state["learning_profile"] = build_learning_profile(student)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": sid}}
    final_state = await graph.ainvoke(state, config=config)
    final_state = await _drive_to_completion(graph, config, final_state)
    return {
        "session_id": sid,
        "response_text": _spoken_text(final_state),
        "audio_uri": final_state.get("audio_response_path") or "",
    }
