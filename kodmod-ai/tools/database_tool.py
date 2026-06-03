"""
KODMOD AI — Database Tool
=========================

A narrow set of safe DB operations exposed to agents — *not* an arbitrary
SQL escape hatch. The tool surface is restricted to:

- save_session_summary: write the human-readable summary at the end of a
  tutoring session
- log_quiz_attempt: persist a single quiz answer + score
- save_analytics_report: store a generated report
- mark_recommendation_consumed: when the student acts on a recommendation

All other DB writes happen through dedicated helpers in
`memory.long_term` and the SQL schema. We expose this tool only so the
reflection / analytics agents can persist their conclusions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import update

from database.models import AnalyticsReport, LearningSession, QuizAttempt, Recommendation
from database.session import async_session

logger = logging.getLogger(__name__)


async def save_session_summary(session_id: uuid.UUID, summary: str) -> None:
    async with async_session() as session:
        await session.execute(
            update(LearningSession)
            .where(LearningSession.id == session_id)
            .values(summary=summary, ended_at=datetime.utcnow())
        )


async def log_quiz_attempt(
    quiz_session_id: uuid.UUID,
    quiz_question_id: uuid.UUID,
    *,
    student_answer: str,
    score: float,
    is_correct: bool,
    confidence: float = 0.0,
    feedback: Optional[str] = None,
    response_latency_ms: Optional[int] = None,
) -> uuid.UUID:
    async with async_session() as session:
        attempt = QuizAttempt(
            quiz_session_id=quiz_session_id,
            quiz_question_id=quiz_question_id,
            student_answer=student_answer,
            score=score,
            is_correct=is_correct,
            confidence=confidence,
            feedback=feedback,
            response_latency_ms=response_latency_ms,
        )
        session.add(attempt)
        await session.flush()
        return attempt.id


async def save_analytics_report(
    *,
    student_id: Optional[uuid.UUID] = None,
    classroom_id: Optional[uuid.UUID] = None,
    report_type: str,
    payload: dict,
) -> uuid.UUID:
    async with async_session() as session:
        report = AnalyticsReport(
            student_id=student_id,
            classroom_id=classroom_id,
            report_type=report_type,
            payload=payload,
        )
        session.add(report)
        await session.flush()
        return report.id


async def mark_recommendation_consumed(recommendation_id: uuid.UUID) -> None:
    async with async_session() as session:
        await session.execute(
            update(Recommendation)
            .where(Recommendation.id == recommendation_id)
            .values(consumed=True)
        )
