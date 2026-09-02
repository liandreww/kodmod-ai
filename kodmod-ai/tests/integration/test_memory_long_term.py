"""Stage 3 §2 — memory/long_term.py against real Postgres.

Spec: docs/testplan/03-integration.md §2 (KM-INT-020..026).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]


# --------------------------------------------------------------------------- #
# KM-INT-020 — load_profile for a fresh student
# --------------------------------------------------------------------------- #
async def test_km_int_020_load_profile_fresh(make_student) -> None:  # type: ignore[no-untyped-def]
    from memory.long_term import load_profile

    st = await make_student(full_name="Budi", preferred_language="id")
    profile = await load_profile(st.id)
    assert profile["full_name"] == "Budi"
    assert profile["preferred_language"] == "id"
    assert profile["accessibility_profile"] == "blind"
    assert profile["voice_settings"] == {}
    assert profile["mastery"] == {}
    assert profile["streak_days"] == 0


# --------------------------------------------------------------------------- #
# KM-INT-021 — update_mastery UPSERTs one row per (student, concept)
# --------------------------------------------------------------------------- #
async def test_km_int_021_update_mastery_upsert(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session
    from memory.long_term import update_mastery

    st = await make_student()
    cid = concept_ids["pecahan"]

    await update_mastery(st.id, cid, new_mastery=0.4, confidence=0.5)
    await update_mastery(st.id, cid, new_mastery=0.7, confidence=0.6)

    async with async_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT mastery, n_attempts FROM mastery_scores "
                    "WHERE student_id=CAST(:sid AS uuid) AND concept_id=CAST(:cid AS uuid)"
                ),
                {"sid": str(st.id), "cid": str(cid)},
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].mastery == pytest.approx(0.7)
    assert rows[0].n_attempts == 2  # 1 on insert, + n_increment on conflict


# --------------------------------------------------------------------------- #
# KM-INT-022 — fetch_weak_concepts returns the 5 lowest, ascending
# --------------------------------------------------------------------------- #
async def test_km_int_022_fetch_weak_concepts(make_student, concept_ids, seed_mastery) -> None:  # type: ignore[no-untyped-def]
    from memory.long_term import fetch_weak_concepts

    st = await make_student()
    slugs = list(concept_ids)[:6]
    values = [0.9, 0.1, 0.5, 0.3, 0.7, 0.2]
    await seed_mastery(st.id, {concept_ids[s]: v for s, v in zip(slugs, values, strict=True)})

    weak = await fetch_weak_concepts(st.id, n=5)
    assert len(weak) == 5
    masteries = [w["mastery"] for w in weak]
    assert masteries == sorted(masteries)
    assert masteries[0] == pytest.approx(0.1)


# --------------------------------------------------------------------------- #
# KM-INT-023 — _compute_streak over consecutive / gapped sessions
# --------------------------------------------------------------------------- #
async def test_km_int_023_compute_streak(make_student) -> None:  # type: ignore[no-untyped-def]
    from database.models import LearningSession
    from database.session import async_session
    from memory.long_term import load_profile

    st = await make_student()
    today = datetime.now(UTC)
    # sessions today, -1d, -2d  (streak 3), then a gap, then -5d
    offsets = [0, 1, 2, 5]
    async with async_session() as s:
        for off in offsets:
            s.add(LearningSession(student_id=st.id, started_at=today - timedelta(days=off)))

    profile = await load_profile(st.id)
    assert profile["streak_days"] == 3


# --------------------------------------------------------------------------- #
# KM-INT-024 — record_misconception + fetch_open_misconceptions
# --------------------------------------------------------------------------- #
async def test_km_int_024_misconceptions(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from memory.long_term import fetch_open_misconceptions, record_misconception

    st = await make_student()
    await record_misconception(st.id, concept_ids["pecahan"], "menyamakan penyebut lupa pembilang")

    open_ = await fetch_open_misconceptions(st.id)
    assert len(open_) == 1
    assert open_[0]["description"].startswith("menyamakan")
    assert open_[0]["concept_id"] == str(concept_ids["pecahan"])


# --------------------------------------------------------------------------- #
# KM-INT-025 — log_interaction stores metadata in the "metadata" column
# --------------------------------------------------------------------------- #
async def test_km_int_025_log_interaction_metadata(make_student) -> None:  # type: ignore[no-untyped-def]
    from database.models import LearningSession
    from database.session import async_session
    from memory.long_term import log_interaction

    st = await make_student()
    async with async_session() as s:
        ls = LearningSession(student_id=st.id)
        s.add(ls)
        await s.flush()
        session_id = ls.id

    await log_interaction(
        session_id,
        role="student",
        text="apa itu pecahan",
        intent="tutoring",
        metadata={"emotion": "engaged"},
    )
    async with async_session() as s:
        row = (
            await s.execute(
                text('SELECT "metadata", role, intent FROM interaction_logs WHERE session_id=:sid'),
                {"sid": str(session_id)},
            )
        ).one()
    assert row.metadata == {"emotion": "engaged"}
    assert row.role == "student"
    assert row.intent == "tutoring"


# --------------------------------------------------------------------------- #
# KM-INT-026 — store_recommendation + fetch_active_recommendations(limit=5)
# --------------------------------------------------------------------------- #
async def test_km_int_026_recommendations(make_student) -> None:  # type: ignore[no-untyped-def]
    from memory.long_term import fetch_active_recommendations, store_recommendation

    st = await make_student()
    for i in range(6):
        await store_recommendation(
            st.id, kind="practice", title=f"Rec {i}", body="latihan", priority=(i % 3) + 1
        )
    active = await fetch_active_recommendations(st.id, limit=5)
    assert len(active) == 5
    priorities = [r["priority"] for r in active]
    assert priorities == sorted(priorities)  # ordered by priority asc
