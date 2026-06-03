"""
KODMOD AI — Episodic Memory
===========================

Captures *notable* events worth remembering across sessions:

- "Student mastered fractions today" (mastery >= 0.8 transition)
- "Student struggled 3 quizzes in a row on photosynthesis"
- "Student showed strong engagement during history Q&A"
- "Student reported frustration during algebra"

These episodes feed:
- Teacher dashboard alerts
- Recommendation agent (next session priming)
- Reflection agent (long-running self-evaluation)

Storage piggybacks on `analytics_reports` with report_type='episode'.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import desc, select

from database.models import AnalyticsReport
from database.session import async_session

logger = logging.getLogger(__name__)

EpisodeKind = Literal[
    "mastery_unlocked",
    "concept_struggled",
    "high_engagement",
    "frustration_detected",
    "milestone",
    "intervention_recommended",
]


async def record_episode(
    student_id: uuid.UUID,
    kind: EpisodeKind,
    *,
    title: str,
    description: str,
    payload: Optional[dict] = None,
) -> uuid.UUID:
    """Persist an episode. Returns the report id."""
    async with async_session() as session:
        report = AnalyticsReport(
            student_id=student_id,
            report_type=f"episode:{kind}",
            payload={
                "kind": kind,
                "title": title,
                "description": description,
                "details": payload or {},
                "ts": datetime.utcnow().isoformat(),
            },
        )
        session.add(report)
        await session.flush()
        logger.info(
            "Recorded episode kind=%s student=%s title=%r", kind, student_id, title
        )
        return report.id


async def fetch_recent_episodes(
    student_id: uuid.UUID,
    *,
    kinds: Optional[list[EpisodeKind]] = None,
    limit: int = 10,
) -> list[dict]:
    """Return the most recent episodes (optionally filtered by kind)."""
    async with async_session() as session:
        stmt = (
            select(AnalyticsReport)
            .where(AnalyticsReport.student_id == student_id)
            .where(AnalyticsReport.report_type.like("episode:%"))
            .order_by(desc(AnalyticsReport.generated_at))
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()

    out = []
    for r in rows:
        payload = r.payload or {}
        if kinds and payload.get("kind") not in kinds:
            continue
        out.append({
            "id": str(r.id),
            "kind": payload.get("kind"),
            "title": payload.get("title"),
            "description": payload.get("description"),
            "details": payload.get("details", {}),
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        })
    return out


# Convenience: thresholded auto-recorders the analytics agent can call.
async def maybe_record_mastery_unlock(
    student_id: uuid.UUID,
    concept_name: str,
    mastery: float,
) -> None:
    if mastery < 0.8:
        return
    await record_episode(
        student_id,
        kind="mastery_unlocked",
        title=f"Menguasai konsep {concept_name}",
        description=(
            f"Siswa mencapai tingkat penguasaan {mastery:.0%} pada konsep "
            f"{concept_name}. Bagus sekali — siap untuk materi berikutnya."
        ),
        payload={"concept": concept_name, "mastery": mastery},
    )


async def maybe_record_struggle(
    student_id: uuid.UUID,
    concept_name: str,
    consecutive_failures: int,
) -> None:
    if consecutive_failures < 3:
        return
    await record_episode(
        student_id,
        kind="concept_struggled",
        title=f"Kesulitan pada {concept_name}",
        description=(
            f"Siswa salah menjawab {consecutive_failures} kali berturut-turut "
            f"pada konsep {concept_name}. Disarankan sesi remediasi."
        ),
        payload={"concept": concept_name, "consecutive_failures": consecutive_failures},
    )
