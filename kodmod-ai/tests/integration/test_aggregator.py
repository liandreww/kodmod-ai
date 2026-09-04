"""Stage 3 §6 — analytics/aggregator.py (Student + Classroom rollups).

Spec: docs/testplan/03-integration.md §6 (KM-INT-070..079).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]


async def _seed_activity(student_id, concept_id, *, n_sessions=2, n_correct=2, n_wrong=1):  # type: ignore[no-untyped-def]
    from database.models import (
        LearningSession,
        MasteryScore,
        Misconception,
        QuizAttempt,
        QuizQuestion,
        QuizSession,
    )
    from database.session import async_session

    now = datetime.now(UTC)
    async with async_session() as s:
        for i in range(n_sessions):
            s.add(
                LearningSession(
                    student_id=student_id,
                    started_at=now - timedelta(days=i, minutes=20),
                    ended_at=now - timedelta(days=i),
                )
            )
        qs = QuizSession(
            student_id=student_id, concept_id=concept_id, total_questions=n_correct + n_wrong
        )
        s.add(qs)
        await s.flush()
        for i in range(n_correct + n_wrong):
            q = QuizQuestion(
                quiz_session_id=qs.id,
                order_index=i,
                question=f"q{i}",
                question_type="mcq",
                correct_answer="A",
                concept_id=concept_id,
            )
            s.add(q)
            await s.flush()
            s.add(
                QuizAttempt(
                    quiz_session_id=qs.id,
                    quiz_question_id=q.id,
                    student_answer="A",
                    score=1.0 if i < n_correct else 0.0,
                    is_correct=i < n_correct,
                    answered_at=now,
                )
            )
        s.add(
            MasteryScore(student_id=student_id, concept_id=concept_id, mastery=0.55, n_attempts=3)
        )
        s.add(
            Misconception(
                student_id=student_id, concept_id=concept_id, description="salah samakan penyebut"
            )
        )


async def test_km_int_070_student_summary_rollups(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from analytics.aggregator import StudentAggregator

    st = await make_student()
    await _seed_activity(st.id, concept_ids["pecahan"], n_sessions=2, n_correct=2, n_wrong=1)

    out = await StudentAggregator().summarise(student_id=st.id, window="week")
    assert out["n_sessions"] == 2
    assert out["n_quiz_attempts"] == 3
    assert out["avg_quiz_score"] == pytest.approx(2 / 3, abs=1e-3)
    assert out["quiz_accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert 0.0 <= out["overall_mastery"] <= 1.0
    assert len(out["weak_concepts"]) >= 1
    assert out["open_misconceptions"]
    assert 0.0 <= out["engagement_index"] <= 1.0
    assert out["total_minutes"] > 0


async def test_km_int_071_engagement_index_formula(make_student, concept_ids) -> None:  # type: ignore[no-untyped-def]
    from analytics.aggregator import StudentAggregator, _window_start

    st = await make_student()
    await _seed_activity(st.id, concept_ids["pecahan"], n_sessions=2, n_correct=1, n_wrong=0)
    out = await StudentAggregator().summarise(student_id=st.id, window="week")

    start = _window_start("week")
    days = max(1, (datetime.utcnow() - start).days)
    sessions_per_day = out["n_sessions"] / days
    avg_minutes = out["total_minutes"] / max(1, out["n_sessions"])
    expected = min(1.0, sessions_per_day * avg_minutes / 30.0)
    assert out["engagement_index"] == pytest.approx(round(expected, 3), abs=1e-3)


async def test_km_int_072_student_not_found() -> None:
    from analytics.aggregator import StudentAggregator

    out = await StudentAggregator().summarise(student_id=uuid.uuid4())
    assert out == {"error": "student_not_found"}


async def test_km_int_073_include_recommendations(make_student) -> None:  # type: ignore[no-untyped-def]
    from analytics.aggregator import StudentAggregator
    from memory.long_term import store_recommendation

    st = await make_student()
    await store_recommendation(
        st.id, kind="practice", title="Latihan pecahan", body="kerjakan 5 soal"
    )

    on = await StudentAggregator().summarise(student_id=st.id, include_recommendations=True)
    off = await StudentAggregator().summarise(student_id=st.id, include_recommendations=False)
    assert (
        on["active_recommendations"]
        and on["active_recommendations"][0]["title"] == "Latihan pecahan"
    )
    assert "active_recommendations" not in off


def test_km_int_074_window_start_all_windows() -> None:
    from analytics.aggregator import _window_start

    assert _window_start("all") is None
    today = _window_start("today")
    assert today is not None and today.hour == 0 and today.minute == 0
    week = _window_start("week")
    month = _window_start("month")
    now = datetime.utcnow()
    assert 6 <= (now - week).days <= 7
    assert 29 <= (now - month).days <= 30


@pytest.mark.known_bug(
    "#20 — ClassroomAggregator.summarise queries table classroom_enrollment, which exists "
    "only in schema.sql and is not in the ORM / test schema"
)
async def test_km_int_078_classroom_summary_roster(
    make_student, teacher_factory, concept_ids
) -> None:  # type: ignore[no-untyped-def]
    from analytics.aggregator import ClassroomAggregator
    from database.models import Classroom, ClassroomEnrollment
    from database.session import async_session

    st = await make_student()
    await _seed_activity(st.id, concept_ids["pecahan"])
    async with async_session() as s:
        room = Classroom(name="Kelas 7A")
        s.add(room)
        await s.flush()
        room_id = room.id
        s.add(ClassroomEnrollment(classroom_id=room_id, student_id=st.id))

    out = await ClassroomAggregator().summarise(classroom_id=room_id)
    assert out.get("n_students") == 1
    assert "class_weak_concepts" in out


async def test_km_int_079_classroom_not_found() -> None:
    from analytics.aggregator import ClassroomAggregator

    out = await ClassroomAggregator().summarise(classroom_id=uuid.uuid4())
    assert out == {"error": "classroom_not_found"}
