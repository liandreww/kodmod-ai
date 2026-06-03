"""
KODMOD AI — Student Routes
==========================

- GET  /student/me            -> current student profile
- POST /student               -> create a student (admin / onboarding)
- GET  /student/{id}/profile  -> extended profile (mastery, weak concepts)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import current_student, db_session
from database.models import Student
from memory.long_term import fetch_weak_concepts, load_profile
from models.student import StudentCreate, StudentOut, StudentProfileOut

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/me", response_model=StudentOut)
async def get_me(student: Student = Depends(current_student)) -> Student:
    return student


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreate,
    session: AsyncSession = Depends(db_session),
) -> Student:
    student = Student(
        full_name=payload.full_name,
        email=payload.email,
        grade_level=payload.grade_level,
        accessibility_profile=payload.accessibility_profile,
        preferred_language=payload.preferred_language,
        voice_settings=payload.voice_settings or {},
    )
    session.add(student)
    await session.flush()
    await session.refresh(student)
    return student


@router.get("/{student_id}/profile", response_model=StudentProfileOut)
async def get_student_profile(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
) -> StudentProfileOut:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    profile = await load_profile(student_id)
    weak = await fetch_weak_concepts(student_id, n=5)
    weak_names = [w.get("concept_id", "") for w in weak]
    overall = (
        sum(profile.get("mastery", {}).values()) / max(1, len(profile.get("mastery", {})))
        if profile.get("mastery")
        else 0.0
    )

    return StudentProfileOut(
        id=student.id,
        full_name=student.full_name,
        email=student.email,
        grade_level=student.grade_level,
        accessibility_profile=student.accessibility_profile,
        preferred_language=student.preferred_language,
        voice_settings=student.voice_settings or {},
        created_at=student.created_at,
        updated_at=student.updated_at,
        overall_mastery=overall,
        weak_concepts=weak_names,
        strong_concepts=[],
        streak_days=profile.get("streak_days", 0),
        last_active_at=datetime.utcnow(),
    )
