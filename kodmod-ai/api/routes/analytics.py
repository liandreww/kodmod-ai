"""
KODMOD AI — Analytics Routes
============================

Endpoints feeding the Student Dashboard and Teacher Dashboard
(Cluster Analytics & Reporting).

- GET /analytics/student/{id}            -> student rollup
- GET /analytics/student/{id}/spoken     -> spoken summary (audio-friendly text)
- GET /analytics/classroom/{id}          -> classroom rollup
- GET /analytics/classroom/{id}/alerts   -> classroom alerts for teacher
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from analytics.aggregator import ClassroomAggregator, StudentAggregator
from analytics.insights import (
    generate_classroom_alerts,
    generate_student_spoken_summary,
    generate_teacher_summary,
)
from api.dependencies import current_student, current_teacher
from database.models import Student, Teacher

logger = logging.getLogger(__name__)
router = APIRouter()

WindowName = Literal["today", "week", "month", "all"]


@router.get("/student/{student_id}")
async def student_analytics(
    student_id: uuid.UUID,
    window: WindowName = Query("week"),
    student: Student = Depends(current_student),
) -> dict:
    if student.id != student_id:
        # In future: allow if requester is the teacher of this student.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot read another student's analytics")
    return await StudentAggregator().summarise(student_id=student_id, window=window)


@router.get("/student/{student_id}/spoken")
async def student_analytics_spoken(
    student_id: uuid.UUID,
    window: WindowName = Query("week"),
    student: Student = Depends(current_student),
) -> dict:
    if student.id != student_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot read another student's analytics")
    rollup = await StudentAggregator().summarise(student_id=student_id, window=window)
    spoken = generate_student_spoken_summary(rollup)
    return {"spoken": spoken, "rollup": rollup}


@router.get("/classroom/{classroom_id}")
async def classroom_analytics(
    classroom_id: uuid.UUID,
    window: WindowName = Query("week"),
    teacher: Teacher = Depends(current_teacher),
) -> dict:
    return await ClassroomAggregator().summarise(classroom_id=classroom_id, window=window)


@router.get("/classroom/{classroom_id}/alerts")
async def classroom_alerts(
    classroom_id: uuid.UUID,
    window: WindowName = Query("week"),
    teacher: Teacher = Depends(current_teacher),
) -> dict:
    rollup = await ClassroomAggregator().summarise(classroom_id=classroom_id, window=window)
    alerts = generate_classroom_alerts(rollup)
    per_student_summaries = [
        generate_teacher_summary(
            await StudentAggregator().summarise(
                student_id=uuid.UUID(s["student_id"]),
                window=window,
                include_recommendations=False,
            )
        )
        for s in rollup.get("students", [])
    ]
    return {"alerts": alerts, "per_student": per_student_summaries, "headline": rollup}
