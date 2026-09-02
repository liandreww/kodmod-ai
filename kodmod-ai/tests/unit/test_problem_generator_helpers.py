"""KM-UNIT-050..055 — pure problem-generator heuristics (agents/problem_generator.py).

Oracle: the functions + the QuizQuestion TypedDict in graphs/state.py.
Spec: docs/testplan/01-unit.md §4.
"""

from __future__ import annotations

import pytest

from agents.problem_generator import (
    _decide_n_questions,
    _fallback_question,
    _infer_concept,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("emotion", ["fatigued", "frustrated"])
def test_decide_n_questions_short_when_low_energy(emotion: str) -> None:  # KM-UNIT-050
    assert _decide_n_questions({"emotional_state": emotion}) == 3


def test_decide_n_questions_long_when_motivated() -> None:  # KM-UNIT-051
    assert _decide_n_questions({"emotional_state": "motivated"}) == 7


@pytest.mark.parametrize("state", [{"emotional_state": "neutral"}, {}])
def test_decide_n_questions_default(state: dict) -> None:  # KM-UNIT-052
    assert _decide_n_questions(state) == 5


def test_infer_concept_picks_weakest() -> None:  # KM-UNIT-053
    assert _infer_concept({"mastery_scores": {"a": 0.9, "b": 0.2}}) == "b"


def test_infer_concept_empty_falls_back_to_general() -> None:  # KM-UNIT-054
    assert _infer_concept({"mastery_scores": {}}) == "general"
    assert _infer_concept({}) == "general"


def test_fallback_question_is_valid_quiz_question() -> None:  # KM-UNIT-055
    q = _fallback_question("pecahan", "easy")
    for key in ("question_id", "text", "type", "concept_id", "difficulty"):
        assert key in q
    assert q["concept_id"] == "pecahan"
    assert q["difficulty"] == "easy"
    assert q["type"] == "explain"
    assert q["question_id"]
