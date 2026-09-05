"""
KODMOD AI — Chat Routes
=======================

- POST   /chat/message         -> one turn, single response (no streaming)
- GET    /chat/sessions        -> the student's own conversation history
- GET    /chat/sessions/{id}   -> one conversation, turn by turn
- DELETE /chat/sessions/{id}   -> delete a conversation

The streaming path is `/ws/chat`; this REST route exists as a fallback for
clients that cannot hold a socket open, and it is what makes the backend
testable without a WebSocket client.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat_service import (
    build_turn_state,
    close_session,
    log_turn,
    open_session,
    reply_text,
    sources,
    update_session_mode,
)
from api.dependencies import db_session, require_student
from database.models import InteractionLog, LearningSession, Subject, User

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None


class ChatMessageResponse(BaseModel):
    session_id: uuid.UUID
    text: str
    intent: str
    next_action: str
    sources: list[dict] = Field(default_factory=list)
    latency_ms: int
    quiz_progress: dict | None = None


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: Request,
    body: ChatMessageRequest,
    student: User = Depends(require_student),
) -> ChatMessageResponse:
    """Run one conversational turn and return the whole answer at once."""
    started = time.perf_counter()
    session_id = await open_session(
        student_id=student.id,
        session_id=body.session_id,
        subject_id=body.subject_id,
        first_text=body.text,
    )
    state = await build_turn_state(
        student=student, session_id=session_id, text=body.text, subject_id=body.subject_id
    )

    graph = request.app.state.graph
    final = await graph.ainvoke(state, config={"configurable": {"thread_id": str(session_id)}})

    answer = reply_text(final)
    latency_ms = int((time.perf_counter() - started) * 1000)

    await log_turn(session_id, role="student", text=body.text, intent=final.get("intent"))
    await log_turn(
        session_id,
        role="assistant",
        text=answer,
        intent=final.get("intent"),
        latency_ms=latency_ms,
    )
    await update_session_mode(session_id, final.get("intent"))

    quiz_progress = (
        {
            "index": final.get("current_question_index", 0),
            "total": len(final.get("quiz_questions") or []),
        }
        if final.get("intent") == "quiz" and final.get("quiz_questions")
        else None
    )

    return ChatMessageResponse(
        session_id=session_id,
        text=answer,
        intent=str(final.get("intent") or "unknown"),
        next_action=str(final.get("next_action") or "end"),
        sources=sources(final),
        latency_ms=latency_ms,
        quiz_progress=quiz_progress,
    )


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    student: User = Depends(require_student),
    session: AsyncSession = Depends(db_session),
) -> list[dict]:
    """The student's conversations, newest first."""
    rows = (
        await session.execute(
            select(LearningSession, Subject.name)
            .outerjoin(Subject, LearningSession.subject_id == Subject.id)
            .where(LearningSession.student_id == student.id)
            .order_by(LearningSession.started_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(ls.id),
            "title": ls.title or "Sesi tanpa judul",
            "subject_id": str(ls.subject_id) if ls.subject_id else None,
            "subject_name": subject_name,
            "started_at": ls.started_at.isoformat() if ls.started_at else None,
        }
        for ls, subject_name in rows
    ]


async def _own_session_or_404(
    session: AsyncSession, session_id: uuid.UUID, student: User
) -> LearningSession:
    row = (
        await session.execute(
            select(LearningSession).where(
                LearningSession.id == session_id,
                LearningSession.student_id == student.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation.")
    return row


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    student: User = Depends(require_student),
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Replay one conversation so the student can pick it back up."""
    row = await _own_session_or_404(session, session_id, student)
    turns = (
        (
            await session.execute(
                select(InteractionLog)
                .where(InteractionLog.session_id == session_id)
                .order_by(InteractionLog.timestamp)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(row.id),
        "title": row.title or "Sesi tanpa judul",
        "subject_id": str(row.subject_id) if row.subject_id else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "turns": [
            {
                "role": t.role,
                "text": t.text,
                "intent": t.intent,
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            }
            for t in turns
        ],
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    student: User = Depends(require_student),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Delete a conversation and its turns."""
    row = await _own_session_or_404(session, session_id, student)
    await session.delete(row)
    await session.flush()


@router.post("/sessions/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(
    session_id: uuid.UUID,
    student: User = Depends(require_student),
) -> None:
    """Mark a conversation finished."""
    if not await close_session(session_id, student.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation.")
