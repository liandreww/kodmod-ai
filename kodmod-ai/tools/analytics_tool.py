"""
KODMOD AI — Analytics Tool
==========================

Tool wrapper around the analytics aggregator. Agents call this to fetch
summary data — e.g. when a student asks "bagaimana progress saya
minggu ini?" the tutor can call this tool and respond with a spoken
summary.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StudentAnalyticsInput(BaseModel):
    student_id: str
    window: Literal["today", "week", "month", "all"] = "week"
    include_recommendations: bool = True


async def fetch_student_analytics(
    student_id: str,
    *,
    window: str = "week",
    include_recommendations: bool = True,
) -> dict:
    from analytics.aggregator import StudentAggregator

    agg = StudentAggregator()
    return await agg.summarise(
        student_id=uuid.UUID(student_id),
        window=window,
        include_recommendations=include_recommendations,
    )


def get_student_analytics_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=fetch_student_analytics,
        name="get_student_analytics",
        description=(
            "Compute a learning-analytics summary for a student over a time window. "
            "Returns mastery overview, weak/strong concepts, engagement, and (if "
            "requested) personalised recommendations. Use when the student asks about "
            "their progress."
        ),
        args_schema=StudentAnalyticsInput,
    )


class ClassroomAnalyticsInput(BaseModel):
    classroom_id: str
    window: Literal["week", "month", "all"] = "week"


async def fetch_classroom_analytics(classroom_id: str, *, window: str = "week") -> dict:
    from analytics.aggregator import ClassroomAggregator

    return await ClassroomAggregator().summarise(
        classroom_id=uuid.UUID(classroom_id), window=window
    )


def get_classroom_analytics_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=fetch_classroom_analytics,
        name="get_classroom_analytics",
        description=(
            "Compute aggregate analytics for an entire classroom (used by the teacher "
            "dashboard)."
        ),
        args_schema=ClassroomAnalyticsInput,
    )
