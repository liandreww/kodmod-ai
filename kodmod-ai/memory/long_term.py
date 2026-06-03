"""
KODMOD AI — Long-Term Memory (PostgreSQL)
=========================================

Persistent learner profile and mastery graph. Wraps the SQLAlchemy
session helpers so agents can call `load_profile(student_id)` /
`update_mastery(...)` without touching ORM details.

This is the canonical store for:
- Mastery scores per concept (BKT-style)
- Detected misconceptions
- Learning preferences (preferred_language, voice_settings)
- Aggregate statistics used by the dashboards
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import (
    InteractionLog,
    LearningSession,
    MasteryScore,
    Misconception,
    Recommendation,
    Student,
)
from database.session import async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- profile --
async def load_profile(student_id: uuid.UUID) -> dict:
    """Return a flat dict matching `LearningProfile` TypedDict."""
    async with async_session() as session:
        student = await session.get(Student, student_id)
        if not student:
            return {}

        mastery_rows = (
            await session.execute(
                select(MasteryScore).where(MasteryScore.student_id == student_id)
            )
        ).scalars().all()
        mastery = {str(m.concept_id): float(m.mastery) for m in mastery_rows}

        # Streak: consecutive days with at least one session.
        streak_days = await _compute_streak(session, student_id)

        return {
            "student_id": str(student.id),
            "full_name": student.full_name,
            "preferred_language": student.preferred_language,
            "accessibility_profile": student.accessibility_profile,
            "voice_settings": student.voice_settings or {},
            "mastery": mastery,
            "streak_days": streak_days,
        }


async def _compute_streak(session, student_id: uuid.UUID) -> int:
    sessions = (
        await session.execute(
            select(LearningSession.started_at)
            .where(LearningSession.student_id == student_id)
            .order_by(desc(LearningSession.started_at))
            .limit(60)
        )
    ).scalars().all()

    if not sessions:
        return 0

    today = datetime.utcnow().date()
    days = sorted({s.date() for s in sessions}, reverse=True)
    streak = 0
    expected = today
    for d in days:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d == expected + timedelta(days=1):
            # tolerate today not yet recorded
            continue
        else:
            break
    return streak


# ------------------------------------------------------------- mastery --
async def update_mastery(
    student_id: uuid.UUID,
    concept_id: uuid.UUID,
    *,
    new_mastery: float,
    confidence: float = 0.0,
    n_increment: int = 1,
) -> None:
    """UPSERT the mastery row for (student, concept)."""
    async with async_session() as session:
        stmt = pg_insert(MasteryScore.__table__).values(
            student_id=student_id,
            concept_id=concept_id,
            mastery=new_mastery,
            confidence=confidence,
            n_attempts=n_increment,
            last_seen=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["student_id", "concept_id"],
            set_={
                "mastery": new_mastery,
                "confidence": confidence,
                "n_attempts": MasteryScore.__table__.c.n_attempts + n_increment,
                "last_seen": datetime.utcnow(),
            },
        )
        await session.execute(stmt)


async def fetch_weak_concepts(student_id: uuid.UUID, n: int = 5) -> list[dict]:
    async with async_session() as session:
        rows = (
            await session.execute(
                select(MasteryScore)
                .where(MasteryScore.student_id == student_id)
                .order_by(MasteryScore.mastery.asc())
                .limit(n)
            )
        ).scalars().all()
        return [
            {"concept_id": str(r.concept_id), "mastery": float(r.mastery)} for r in rows
        ]


# ------------------------------------------------------- misconceptions --
async def record_misconception(
    student_id: uuid.UUID,
    concept_id: uuid.UUID,
    description: str,
) -> None:
    async with async_session() as session:
        session.add(Misconception(
            student_id=student_id, concept_id=concept_id, description=description,
        ))


async def fetch_open_misconceptions(student_id: uuid.UUID) -> list[dict]:
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Misconception)
                .where(Misconception.student_id == student_id, Misconception.resolved.is_(False))
                .order_by(Misconception.detected_at.desc())
                .limit(20)
            )
        ).scalars().all()
        return [
            {
                "id": str(r.id),
                "concept_id": str(r.concept_id),
                "description": r.description,
                "detected_at": r.detected_at.isoformat(),
            }
            for r in rows
        ]


# -------------------------------------------------------- interactions --
async def log_interaction(
    session_id: uuid.UUID,
    *,
    role: str,
    text: str,
    intent: Optional[str] = None,
    audio_path: Optional[str] = None,
    latency_ms: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    async with async_session() as session:
        session.add(
            InteractionLog(
                session_id=session_id,
                role=role,
                text=text,
                intent=intent,
                audio_path=audio_path,
                latency_ms=latency_ms,
                metadata_=metadata or {},
            )
        )


# ------------------------------------------------------- recommendations --
async def store_recommendation(
    student_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str,
    target_concept_id: Optional[uuid.UUID] = None,
    priority: int = 1,
) -> uuid.UUID:
    async with async_session() as session:
        rec = Recommendation(
            student_id=student_id,
            kind=kind,
            title=title,
            body=body,
            target_concept_id=target_concept_id,
            priority=priority,
        )
        session.add(rec)
        await session.flush()
        return rec.id


async def fetch_active_recommendations(student_id: uuid.UUID, limit: int = 5) -> list[dict]:
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Recommendation)
                .where(Recommendation.student_id == student_id, Recommendation.consumed.is_(False))
                .order_by(Recommendation.priority.asc(), Recommendation.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            {
                "id": str(r.id),
                "kind": r.kind,
                "title": r.title,
                "body": r.body,
                "priority": r.priority,
            }
            for r in rows
        ]
