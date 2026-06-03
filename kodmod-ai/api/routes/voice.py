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
from graphs.state import initial_state
from models.student import StudentOut
from voice.streaming import save_upload

log = logging.getLogger(__name__)
router = APIRouter()


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

    sid = session_id or str(uuid4())
    audio_path = await save_upload(audio)

    state = initial_state(
        session_id=sid,
        student_id=student.id,
        audio_input_path=str(audio_path),
    )
    state["learning_profile"] = student.profile

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": sid}}

    final_state = await graph.ainvoke(state, config=config)

    log.info("Voice chat turn complete (session=%s, last_node=%s)",
             sid, final_state.get("last_node"))

    return {
        "session_id": sid,
        "transcript": final_state.get("transcribed_text"),
        "intent": final_state.get("intent"),
        "response_text": final_state.get("accessible_response")
                       or final_state.get("generated_response"),
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
    state = initial_state(session_id=sid, student_id=student.id)
    state["transcribed_text"] = text
    state["user_input"] = text
    state["learning_profile"] = student.profile

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": sid}}
    final_state = await graph.ainvoke(state, config=config)
    return {
        "session_id": sid,
        "response_text": final_state.get("accessible_response"),
        "audio_uri": final_state.get("audio_response_path"),
    }
