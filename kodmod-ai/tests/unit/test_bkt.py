"""KM-UNIT-020..030 — BKT mastery math (analytics/student_model.StudentModel).

Rewrite of the old test_student_model.py (finding #18 — its `update()` / `apply_decay()`
signatures were stale). Oracle: the closed-form update in student_model.py::
    delta     = (attempt_score - prev) * LEARNING_RATE * confidence   # LR=0.25
    new_score = clamp01(prev + delta)                                 # prev defaults 0.5
    new_conf  = min(1.0, conf + 0.05)  per attempt
    decay     = score - DAILY_DECAY * days   (DAILY_DECAY=0.005), floor 0.0

Spec: docs/testplan/01-unit.md §2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analytics.student_model import DAILY_DECAY, LEARNING_RATE, StudentModel

pytestmark = pytest.mark.unit


@pytest.fixture
def model() -> StudentModel:
    return StudentModel(student_id="11111111-1111-1111-1111-111111111111")


async def test_correct_answer_raises_mastery(model: StudentModel) -> None:  # KM-UNIT-020
    model.update("c", 1.0)
    scores = await model.mastery_scores()
    assert scores["c"] == pytest.approx(0.5 + (1.0 - 0.5) * LEARNING_RATE * 0.9)
    assert scores["c"] == pytest.approx(0.6125)


async def test_wrong_answer_dampens_mastery(model: StudentModel) -> None:  # KM-UNIT-021
    model.update("c", 0.0)
    scores = await model.mastery_scores()
    assert scores["c"] == pytest.approx(0.5 + (0.0 - 0.5) * LEARNING_RATE * 0.9)
    assert scores["c"] == pytest.approx(0.3875)


async def test_mastery_bounded_0_1(model: StudentModel) -> None:  # KM-UNIT-022
    for _ in range(50):
        model.update("c", 1.0)
        assert 0.0 <= model._scores["c"] <= 1.0
    for _ in range(50):
        model.update("c", 0.0)
        assert 0.0 <= model._scores["c"] <= 1.0


def test_confidence_accumulates_capped_at_1(model: StudentModel) -> None:  # KM-UNIT-023
    model.update("c", 1.0)
    assert model._confidence["c"] == pytest.approx(0.55)  # 0.5 + 0.05
    model.update("c", 1.0)
    assert model._confidence["c"] == pytest.approx(0.60)
    for _ in range(50):
        model.update("c", 1.0)
    assert model._confidence["c"] == 1.0


def test_attempt_counter_increments(model: StudentModel) -> None:  # KM-UNIT-024
    for _ in range(3):
        model.update("c", 1.0)
    assert model._attempts["c"] == 3


def test_apply_decay_no_args(model: StudentModel) -> None:  # KM-UNIT-025
    model._scores["c"] = 0.8
    model._last_practiced["c"] = datetime.now(UTC) - timedelta(days=30)
    model.apply_decay()
    assert model._scores["c"] == pytest.approx(0.8 - DAILY_DECAY * 30)  # 0.65

    model._scores["floor"] = 0.1
    model._last_practiced["floor"] = datetime.now(UTC) - timedelta(days=30)
    model.apply_decay()
    assert model._scores["floor"] == 0.0  # clamped, never negative


def test_decay_zero_days_is_noop(model: StudentModel) -> None:  # KM-UNIT-026
    model._scores["c"] = 0.7
    model._last_practiced["c"] = datetime.now(UTC)
    model.apply_decay()
    assert model._scores["c"] == 0.7


def test_weak_concepts_ascending_keys_only(model: StudentModel) -> None:  # KM-UNIT-027
    model._scores.update({"a": 0.9, "b": 0.2, "c": 0.5})
    weak = model.weak_concepts(2)
    assert weak == ["b", "c"]
    assert all(isinstance(x, str) for x in weak)
    assert len(model.weak_concepts(3)) == 3


def test_strong_concepts_descending(model: StudentModel) -> None:  # KM-UNIT-028
    model._scores.update({"a": 0.9, "b": 0.2, "c": 0.5})
    assert model.strong_concepts(2) == ["a", "c"]


def test_overall_mastery_is_mean(model: StudentModel) -> None:  # KM-UNIT-029
    assert model.overall_mastery() == 0.0  # empty
    model._scores.update({"a": 0.9, "b": 0.3})
    assert model.overall_mastery() == pytest.approx(0.6)


async def test_mastery_scores_is_async_copy(model: StudentModel) -> None:  # KM-UNIT-030
    model.update("c", 1.0)
    snapshot = await model.mastery_scores()
    assert snapshot == model._scores
    snapshot["injected"] = 1.0
    assert "injected" not in model._scores  # returned a copy, not the internal dict
