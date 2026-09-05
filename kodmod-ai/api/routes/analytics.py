"""
KODMOD AI — Analytics Routes
============================

- GET /analytics/me                      -> the signed-in student's own rollup
- GET /analytics/me/spoken               -> the same, as a short spoken summary
- GET /analytics/student/{id}            -> one student (self, or any teacher)
- GET /analytics/cohort                  -> every student (teacher only)
- GET /analytics/cohort/alerts           -> cohort alerts plus per-student rows
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from analytics.aggregator import CohortAggregator, StudentAggregator
from analytics.insights import generate_cohort_alerts, generate_student_spoken_summary
from api.dependencies import current_user, require_student, require_teacher
from database.models import User

router = APIRouter(tags=["analytics"])

Window = Literal["today", "week", "month", "all"]


@router.get("/me")
async def my_analytics(
    window: Window = Query(default="week"),
    student: User = Depends(require_student),
) -> dict:
    """Your own progress: mastery, quiz accuracy, engagement, misconceptions."""
    return await StudentAggregator().summarise(student_id=student.id, window=window)


@router.get("/me/spoken")
async def my_analytics_spoken(
    window: Window = Query(default="week"),
    student: User = Depends(require_student),
) -> dict:
    """Your own progress, plus a few sentences written to be heard."""
    summary = await StudentAggregator().summarise(student_id=student.id, window=window)
    return {"summary": summary, "spoken": generate_student_spoken_summary(summary)}


@router.get("/student/{student_id}")
async def student_analytics(
    student_id: uuid.UUID,
    window: Window = Query(default="week"),
    user: User = Depends(current_user),
) -> dict:
    """A student may read their own rollup; a teacher may read anyone's."""
    if user.role != "teacher" and user.id != student_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only view your own analytics.")
    return await StudentAggregator().summarise(student_id=student_id, window=window)


@router.get("/cohort")
async def cohort_analytics(
    window: Window = Query(default="week"),
    _: User = Depends(require_teacher),
) -> dict:
    """Averages and weakest concepts across every student."""
    return await CohortAggregator().summarise(window=window)


@router.get("/cohort/alerts")
async def cohort_alerts(
    window: Window = Query(default="week"),
    _: User = Depends(require_teacher),
) -> dict:
    """Cohort-level alerts, plus the rollup they were derived from."""
    rollup = await CohortAggregator().summarise(window=window)
    return {"alerts": generate_cohort_alerts(rollup), "summary": rollup}
