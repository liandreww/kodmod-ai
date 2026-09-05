"""
KODMOD AI — Teacher Routes
==========================

There are no classrooms: a teacher sees every student.

- GET /teacher/students                 -> roster with progress at a glance
- GET /teacher/students/{id}            -> one student in detail
- GET /teacher/students/{id}/sessions   -> their conversations
- GET /teacher/sessions/{id}            -> one full transcript
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analytics.aggregator import CohortAggregator, StudentAggregator
from analytics.insights import generate_teacher_summary
from api.dependencies import db_session, require_teacher
from database.models import InteractionLog, LearningSession, Subject, User
from models.user import UserOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["teacher"], dependencies=[Depends(require_teacher)])

Window = Literal["today", "week", "month", "all"]


async def _student_or_404(session: AsyncSession, student_id: uuid.UUID) -> User:
    student = await session.get(User, student_id)
    if student is None or student.role != "student":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such student.")
    return student


@router.get("/students")
async def list_students(window: Window = Query(default="week")) -> dict:
    """The roster, with each student's mastery, accuracy, and engagement."""
    return await CohortAggregator().summarise(window=window)


@router.get("/students/{student_id}")
async def student_detail(
    student_id: uuid.UUID,
    window: Window = Query(default="month"),
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Everything a teacher needs about one student, minus their credentials."""
    student = await _student_or_404(session, student_id)
    analytics = await StudentAggregator().summarise(student_id=student_id, window=window)
    return {
        "account": UserOut.model_validate(student).model_dump(mode="json"),
        "analytics": analytics,
        "teacher_summary": generate_teacher_summary(analytics),
    }


@router.get("/students/{student_id}/sessions")
async def student_sessions(
    student_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(db_session),
) -> list[dict]:
    """The student's conversations, newest first. Titles only, no turns."""
    await _student_or_404(session, student_id)
    rows = (
        await session.execute(
            select(LearningSession, Subject.name)
            .outerjoin(Subject, LearningSession.subject_id == Subject.id)
            .where(LearningSession.student_id == student_id)
            .order_by(LearningSession.started_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(ls.id),
            "title": ls.title or "Sesi tanpa judul",
            "subject_name": subject_name,
            "mode": ls.mode,
            "started_at": ls.started_at.isoformat() if ls.started_at else None,
            "ended_at": ls.ended_at.isoformat() if ls.ended_at else None,
        }
        for ls, subject_name in rows
    ]


@router.get("/sessions/{session_id}")
async def session_transcript(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """One conversation, turn by turn."""
    learning_session = await session.get(LearningSession, session_id)
    if learning_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")

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
        "id": str(learning_session.id),
        "student_id": str(learning_session.student_id),
        "title": learning_session.title or "Sesi tanpa judul",
        "started_at": learning_session.started_at.isoformat()
        if learning_session.started_at
        else None,
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
