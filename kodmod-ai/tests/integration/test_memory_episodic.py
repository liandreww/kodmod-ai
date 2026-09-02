"""Stage 3 §4 — memory/episodic.py (analytics_reports piggyback).

Spec: docs/testplan/03-integration.md §4 (KM-INT-050..053).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]


async def test_km_int_050_record_episode(make_student) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session
    from memory.episodic import record_episode

    st = await make_student()
    rid = await record_episode(
        st.id,
        "milestone",
        title="Sesi pertama",
        description="Menyelesaikan onboarding",
        payload={"foo": 1},
    )
    async with async_session() as s:
        row = (
            await s.execute(
                text("SELECT report_type, payload FROM analytics_reports WHERE id=:id"),
                {"id": str(rid)},
            )
        ).one()
    assert row.report_type == "episode:milestone"
    assert row.payload["title"] == "Sesi pertama"
    assert row.payload["details"] == {"foo": 1}


async def test_km_int_051_fetch_recent_episodes_filters_non_episodes(make_student) -> None:  # type: ignore[no-untyped-def]
    from database.models import AnalyticsReport
    from database.session import async_session
    from memory.episodic import fetch_recent_episodes, record_episode

    st = await make_student()
    async with async_session() as s:
        s.add(AnalyticsReport(student_id=st.id, report_type="student", payload={"x": 1}))
    await record_episode(st.id, "high_engagement", title="Fokus", description="Sesi bagus")

    eps = await fetch_recent_episodes(st.id)
    assert len(eps) == 1
    assert eps[0]["kind"] == "high_engagement"


async def test_km_int_052_maybe_record_mastery_unlock(make_student) -> None:  # type: ignore[no-untyped-def]
    from memory.episodic import fetch_recent_episodes, maybe_record_mastery_unlock

    st = await make_student()
    await maybe_record_mastery_unlock(st.id, "pecahan", 0.79)
    assert await fetch_recent_episodes(st.id) == []
    await maybe_record_mastery_unlock(st.id, "pecahan", 0.85)
    eps = await fetch_recent_episodes(st.id)
    assert len(eps) == 1 and eps[0]["kind"] == "mastery_unlocked"


async def test_km_int_053_maybe_record_struggle(make_student) -> None:  # type: ignore[no-untyped-def]
    from memory.episodic import fetch_recent_episodes, maybe_record_struggle

    st = await make_student()
    await maybe_record_struggle(st.id, "fotosintesis", 2)
    assert await fetch_recent_episodes(st.id) == []
    await maybe_record_struggle(st.id, "fotosintesis", 3)
    eps = await fetch_recent_episodes(st.id)
    assert len(eps) == 1 and eps[0]["kind"] == "concept_struggled"
