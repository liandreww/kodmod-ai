"""
KODMOD AI — Analytics Aggregator
================================

Computes the metrics that flow into:
- The Learning Analytics Agent (Cluster Analytics & Reporting)
- Teacher Dashboard
- Student Dashboard
- Recommendation Agent inputs

Two aggregators:

- `StudentAggregator`  -> per-student rollups
- `CohortAggregator`   -> rollups across every student (the teacher view)

There are no classrooms: a teacher sees every student.

Each returns a dict that is JSON-serialisable, suitable for both API
responses and storing as `analytics_reports.payload`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import func, select

from database.models import (
    Concept,
    InteractionLog,
    LearningSession,
    MasteryScore,
    Misconception,
    QuizAttempt,
    QuizSession,
    User,
)
from database.session import async_session
from memory.long_term import fetch_active_recommendations

logger = logging.getLogger(__name__)

WindowName = Literal["today", "week", "month", "all"]


def _window_start(window: WindowName) -> datetime | None:
    now = datetime.now(UTC)
    if window == "today":
        return datetime(now.year, now.month, now.day, tzinfo=UTC)
    if window == "week":
        return now - timedelta(days=7)
    if window == "month":
        return now - timedelta(days=30)
    return None  # "all"


@dataclass
class StudentAggregator:
    async def summarise(
        self,
        *,
        student_id: uuid.UUID,
        window: WindowName = "week",
        include_recommendations: bool = True,
    ) -> dict:
        start = _window_start(window)

        async with async_session() as session:
            student = await session.get(User, student_id)
            if student is None:
                return {"error": "student_not_found"}

            # ---- Sessions in window
            sess_q = select(LearningSession).where(LearningSession.student_id == student_id)
            if start:
                sess_q = sess_q.where(LearningSession.started_at >= start)
            sessions = (await session.execute(sess_q)).scalars().all()

            # ---- Quiz attempts in window
            attempts_q = (
                select(QuizAttempt)
                .join(QuizSession, QuizAttempt.quiz_session_id == QuizSession.id)
                .where(QuizSession.student_id == student_id)
            )
            if start:
                attempts_q = attempts_q.where(QuizAttempt.answered_at >= start)
            attempts = (await session.execute(attempts_q)).scalars().all()

            # ---- Mastery snapshot (full, not windowed — mastery is cumulative)
            mastery_rows = (
                await session.execute(
                    select(MasteryScore, Concept)
                    .join(Concept, MasteryScore.concept_id == Concept.id)
                    .where(MasteryScore.student_id == student_id)
                )
            ).all()

            # ---- Open misconceptions
            miscons = (
                await session.execute(
                    select(Misconception, Concept)
                    .join(Concept, Misconception.concept_id == Concept.id)
                    .where(
                        Misconception.student_id == student_id,
                        Misconception.resolved.is_(False),
                    )
                    .order_by(Misconception.detected_at.desc())
                    .limit(10)
                )
            ).all()

            # ---- Engagement counters
            interaction_count = (
                await session.execute(
                    select(func.count(InteractionLog.id))
                    .join(LearningSession, InteractionLog.session_id == LearningSession.id)
                    .where(
                        LearningSession.student_id == student_id,
                        *([InteractionLog.timestamp >= start] if start else []),
                    )
                )
            ).scalar_one()

        # ---------- Compute rollups ----------
        n_sessions = len(sessions)
        total_minutes = sum(
            (
                ((s.ended_at or s.started_at) - s.started_at).total_seconds() / 60.0
                for s in sessions
                if s.started_at
            ),
            0.0,
        )

        n_attempts = len(attempts)
        n_correct = sum(1 for a in attempts if a.is_correct)
        avg_score = (sum(a.score for a in attempts) / n_attempts) if n_attempts else 0.0
        accuracy = (n_correct / n_attempts) if n_attempts else 0.0

        mastery = [
            {
                "concept_id": str(m.concept_id),
                "concept_name": c.name,
                "mastery": float(m.mastery),
                "n_attempts": int(m.n_attempts),
            }
            for m, c in mastery_rows
        ]
        weak = sorted(mastery, key=lambda x: x["mastery"])[:5]
        strong = sorted(mastery, key=lambda x: x["mastery"], reverse=True)[:5]
        overall_mastery = sum(m["mastery"] for m in mastery) / len(mastery) if mastery else 0.0

        # Engagement index (heuristic): sessions/day * avg-session-minutes / 30
        days_in_window = max(1, (datetime.now(UTC) - start).days) if start else 30
        sessions_per_day = n_sessions / days_in_window
        engagement_index = min(1.0, sessions_per_day * (total_minutes / max(1, n_sessions)) / 30.0)

        out: dict = {
            "student_id": str(student_id),
            "student_name": student.full_name,
            "window": window,
            "n_sessions": n_sessions,
            "total_minutes": round(total_minutes, 1),
            "interaction_count": int(interaction_count),
            "n_quiz_attempts": n_attempts,
            "quiz_accuracy": round(accuracy, 3),
            "avg_quiz_score": round(avg_score, 3),
            "overall_mastery": round(overall_mastery, 3),
            "weak_concepts": weak,
            "strong_concepts": strong,
            "open_misconceptions": [
                {
                    "concept_name": c.name,
                    "description": mc.description,
                    "detected_at": mc.detected_at.isoformat(),
                }
                for mc, c in miscons
            ],
            "engagement_index": round(engagement_index, 3),
            "generated_at": datetime.now(UTC).isoformat(),
        }

        if include_recommendations:
            out["active_recommendations"] = await fetch_active_recommendations(student_id, limit=5)
        return out


@dataclass
class CohortAggregator:
    """Rollups across every student. This is what the teacher dashboard shows."""

    async def summarise(self, *, window: WindowName = "week") -> dict:
        async with async_session() as session:
            roster = list(
                (
                    await session.execute(
                        select(User.id).where(User.role == "student", User.is_active.is_(True))
                    )
                )
                .scalars()
                .all()
            )

        # One round trip per student, run concurrently rather than in sequence.
        per_student = await asyncio.gather(
            *(
                StudentAggregator().summarise(
                    student_id=sid, window=window, include_recommendations=False
                )
                for sid in roster
            )
        )
        per_student = [s for s in per_student if "error" not in s]

        if not per_student:
            return {
                "window": window,
                "n_students": 0,
                "students": [],
                "generated_at": datetime.now(UTC).isoformat(),
            }

        n = len(per_student)
        avg_mastery = sum(s["overall_mastery"] for s in per_student) / n
        avg_accuracy = sum(s["quiz_accuracy"] for s in per_student) / n
        avg_engagement = sum(s["engagement_index"] for s in per_student) / n

        # Weakest concepts across the cohort.
        concept_to_scores: dict[str, list[float]] = {}
        for s in per_student:
            for w in s.get("weak_concepts", []):
                concept_to_scores.setdefault(w["concept_name"], []).append(w["mastery"])
        cohort_weak = sorted(
            (
                {"concept_name": k, "avg_mastery": sum(v) / len(v), "n_students": len(v)}
                for k, v in concept_to_scores.items()
            ),
            key=lambda x: cast(float, x["avg_mastery"]),
        )[:5]

        return {
            "window": window,
            "n_students": n,
            "avg_mastery": round(avg_mastery, 3),
            "avg_quiz_accuracy": round(avg_accuracy, 3),
            "avg_engagement_index": round(avg_engagement, 3),
            "cohort_weak_concepts": cohort_weak,
            "students": [
                {
                    "student_id": s["student_id"],
                    "student_name": s["student_name"],
                    "overall_mastery": s["overall_mastery"],
                    "quiz_accuracy": s["quiz_accuracy"],
                    "engagement_index": s["engagement_index"],
                    "n_sessions": s.get("n_sessions", 0),
                    "open_misconceptions": len(s.get("open_misconceptions", [])),
                }
                for s in per_student
            ],
            "generated_at": datetime.now(UTC).isoformat(),
        }
