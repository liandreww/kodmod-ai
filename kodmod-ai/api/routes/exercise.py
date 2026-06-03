"""
KODMOD AI — Exercise Routes
===========================

Endpoints for the Cluster Content & Exercise Management:

- POST /exercise/generate           -> on-demand adaptive question batch
- GET  /exercise/by-concept/{id}    -> static teacher-authored exercises
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import current_student, db_session
from database.models import Exercise, Student
from models.content import (
    ExerciseGenerateRequest,
    ExerciseGenerateResponse,
    ExerciseOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate", response_model=ExerciseGenerateResponse)
async def generate_exercises(
    payload: ExerciseGenerateRequest,
    student: Student = Depends(current_student),
) -> ExerciseGenerateResponse:
    if student.id != payload.student_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mismatched student_id")

    # Lazy import to avoid circular ref between agents and routes.
    from agents.problem_generator import generate_questions_for_student
    from datetime import datetime

    questions = await generate_questions_for_student(
        student_id=payload.student_id,
        concept_id=payload.concept_id,
        n=payload.n_questions,
        difficulty_hint=payload.difficulty,
    )
    return ExerciseGenerateResponse(
        exercises=questions,
        generated_at=datetime.utcnow(),
    )


@router.get("/by-concept/{concept_id}", response_model=list[ExerciseOut])
async def exercises_by_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
) -> list[Exercise]:
    rows = (
        await session.execute(
            select(Exercise).where(Exercise.concept_id == concept_id, Exercise.is_audio_friendly.is_(True))
        )
    ).scalars().all()
    return rows
