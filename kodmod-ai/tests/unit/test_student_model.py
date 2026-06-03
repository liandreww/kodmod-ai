"""Unit tests for analytics/student_model.StudentModel BKT logic."""
from __future__ import annotations

import pytest

from analytics.student_model import StudentModel


@pytest.fixture
def model():
    return StudentModel(student_id="00000000-0000-0000-0000-000000000001")


def test_correct_answer_increases_mastery(model):
    initial = model.mastery_scores().get("c1", 0.0)
    model.update(concept_id="c1", correct=True, score=1.0)
    after = model.mastery_scores()["c1"]
    assert after > initial


def test_wrong_answer_decreases_or_dampens(model):
    model.update(concept_id="c1", correct=True, score=1.0)
    after_correct = model.mastery_scores()["c1"]
    model.update(concept_id="c1", correct=False, score=0.0)
    after_wrong = model.mastery_scores()["c1"]
    assert after_wrong <= after_correct


def test_mastery_bounded_0_1(model):
    for _ in range(50):
        model.update(concept_id="c1", correct=True, score=1.0)
    assert 0.0 <= model.mastery_scores()["c1"] <= 1.0


def test_decay_reduces_mastery_over_time(model):
    model.update(concept_id="c1", correct=True, score=1.0)
    before = model.mastery_scores()["c1"]
    model.apply_decay(days=30)
    after = model.mastery_scores()["c1"]
    assert after < before


def test_weak_concepts_returns_lowest_first(model):
    model.update(concept_id="hard", correct=False, score=0.0)
    model.update(concept_id="easy", correct=True, score=1.0)
    model.update(concept_id="easy", correct=True, score=1.0)
    weak = model.weak_concepts(2)
    assert weak[0]["concept_id"] == "hard"


def test_overall_mastery_average(model):
    model.update(concept_id="a", correct=True, score=1.0)
    model.update(concept_id="b", correct=False, score=0.0)
    overall = model.overall_mastery()
    assert 0.0 <= overall <= 1.0
