"""Stage 3 §5 — analytics/student_model.py round-trips against real Postgres.

Spec: docs/testplan/03-integration.md §5 (KM-INT-060..065).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]


async def test_km_int_060_load_reads_mastery_rows(make_student, concept_ids, seed_mastery) -> None:  # type: ignore[no-untyped-def]
    from analytics.student_model import StudentModel

    st = await make_student()
    cid = concept_ids["pecahan"]
    await seed_mastery(st.id, {cid: 0.6}, n_attempts=4, confidence=0.7)

    m = await StudentModel.load(st.id)
    assert m._scores[str(cid)] == pytest.approx(0.6)
    assert m._confidence[str(cid)] == pytest.approx(0.7)
    assert m._attempts[str(cid)] == 4
    assert str(cid) in m._last_practiced


async def test_km_int_061_load_empty_student() -> None:
    from analytics.student_model import StudentModel

    m = await StudentModel.load(uuid.uuid4())
    assert await m.mastery_scores() == {}
    assert m.overall_mastery() == 0.0


async def test_km_int_062_update_persist_round_trip(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from analytics.student_model import StudentModel
    from database.session import async_session

    st = await make_student()
    cid = str(concept_ids["pecahan"])

    m = await StudentModel.load(st.id)
    m.update(cid, 1.0)
    await m.persist()

    reloaded = await StudentModel.load(st.id)
    assert reloaded._scores[cid] == pytest.approx(m._scores[cid])

    async with async_session() as s:
        n = (
            await s.execute(
                text(
                    "SELECT count(*) FROM mastery_scores WHERE student_id=CAST(:sid AS uuid) "
                    "AND concept_id=CAST(:cid AS uuid)"
                ),
                {"sid": str(st.id), "cid": cid},
            )
        ).scalar_one()
    assert n == 1  # ON CONFLICT (student_id, concept_id) — no duplicate


async def test_km_int_063_persist_sets_attempts_and_last_seen(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from analytics.student_model import StudentModel
    from database.session import async_session

    st = await make_student()
    cid = str(concept_ids["pecahan"])
    m = await StudentModel.load(st.id)
    m.update(cid, 0.8)
    m.update(cid, 0.9)
    await m.persist()

    async with async_session() as s:
        row = (
            await s.execute(
                text(
                    "SELECT n_attempts, last_seen FROM mastery_scores "
                    "WHERE student_id=CAST(:sid AS uuid) AND concept_id=CAST(:cid AS uuid)"
                ),
                {"sid": str(st.id), "cid": cid},
            )
        ).one()
    assert row.n_attempts == 2
    assert row.last_seen is not None


async def test_km_int_064_mastery_scores_is_async_copy(
    make_student, concept_ids, seed_mastery
) -> None:  # type: ignore[no-untyped-def]
    from analytics.student_model import StudentModel

    st = await make_student()
    cid = concept_ids["pecahan"]
    await seed_mastery(st.id, {cid: 0.5})
    m = await StudentModel.load(st.id)
    scores = await m.mastery_scores()
    scores["x"] = 1.0
    assert "x" not in m._scores  # returned a copy


async def test_km_int_065_update_student_model_node_writes_db(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from analytics.student_model import update_student_model_node
    from database.session import async_session

    st = await make_student()
    cid = str(concept_ids["pecahan"])
    state = {
        "student_id": str(st.id),
        "quiz_questions": [{"question_id": "q1", "concept_id": cid}],
        "quiz_attempts": [{"question_id": "q1", "score": 1.0, "confidence": 0.9}],
        "current_question_index": 0,
    }
    out = await update_student_model_node(state)
    assert out["next_action"] == "generate_analytics"
    assert cid in out["mastery_scores"]

    async with async_session() as s:
        val = (
            await s.execute(
                text(
                    "SELECT mastery FROM mastery_scores WHERE student_id=CAST(:sid AS uuid) "
                    "AND concept_id=CAST(:cid AS uuid)"
                ),
                {"sid": str(st.id), "cid": cid},
            )
        ).scalar_one()
    assert val > 0.5  # a correct answer nudged mastery up from the 0.5 prior
