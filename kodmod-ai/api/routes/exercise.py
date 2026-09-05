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

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session, require_student
from database.models import Exercise, User
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
    student: User = Depends(require_student),
) -> ExerciseGenerateResponse:
    """Generate an on-demand adaptive practice batch for the signed-in student."""
    # Lazy import to avoid circular ref between agents and routes.
    from datetime import UTC, datetime

    from agents.problem_generator import generate_questions_for_student

    questions = await generate_questions_for_student(
        student_id=student.id,
        concept_id=payload.concept_id,
        n=payload.n_questions,
        difficulty_hint=payload.difficulty,
    )
    return ExerciseGenerateResponse(
        exercises=questions,
        generated_at=datetime.now(UTC),
    )


@router.get("/by-concept/{concept_id}", response_model=list[ExerciseOut])
async def exercises_by_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    _: User = Depends(require_student),
) -> list[Exercise]:
    """List the audio-friendly teacher-authored exercises for a concept."""
    rows = (
        (
            await session.execute(
                select(Exercise).where(
                    Exercise.concept_id == concept_id, Exercise.is_audio_friendly.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
