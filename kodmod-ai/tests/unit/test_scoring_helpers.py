"""KM-UNIT-040..047 — pure scoring helpers (agents/scoring_agent.py).

Oracle: the functions themselves + the QuizAttempt TypedDict in graphs/state.py.
Spec: docs/testplan/01-unit.md §3.
"""

from __future__ import annotations

import pytest

from agents.scoring_agent import (
    _build_attempt,
    _emit,
    _empty_attempt,
    _find_option_text,
    _score_mcq,
)

pytestmark = pytest.mark.unit

_OPTIONS = ["A. satu", "B. dua", "C. tiga", "D. empat"]


def test_score_mcq_correct_letter() -> None:  # KM-UNIT-040
    score, feedback = _score_mcq("b", "B", _OPTIONS)
    assert score == 1.0
    assert feedback == "Benar."


def test_score_mcq_wrong_letter() -> None:  # KM-UNIT-041
    score, feedback = _score_mcq("C", "B", _OPTIONS)
    assert score == 0.0
    assert feedback == "Belum tepat."


def test_score_mcq_full_option_text_matches() -> None:  # KM-UNIT-042
    score, _ = _score_mcq("B. dua", "B", _OPTIONS)
    assert score == 1.0


def test_score_mcq_empty_options_is_safe() -> None:  # KM-UNIT-043
    # finding #23 fixed: empty `expected` no longer awards blind credit.
    score, feedback = _score_mcq("A", "", options=[])  # must not raise IndexError
    assert score == 0.0
    assert isinstance(feedback, str) and feedback


def test_score_mcq_letter_with_trailing_punctuation() -> None:
    # Regression: "B, dua per empat" (letter immediately followed by a comma,
    # no space) used to fall through every check and score 0.0 despite being
    # correct — the leading-letter regex must not require a space after it.
    score, feedback = _score_mcq("B, dua per empat", "B", _OPTIONS)
    assert score == 1.0
    assert feedback == "Benar."


def test_score_mcq_ambiguous_answer_defers_to_rubric() -> None:
    # No leading letter, and the answer doesn't textually match any option
    # (e.g. answered in a different language than the options) — must not
    # default to wrong; the caller falls back to LLM rubric grading instead.
    score, feedback = _score_mcq("two", "B", _OPTIONS)
    assert score is None
    assert feedback == ""


def test_find_option_text_matches_letter() -> None:
    assert _find_option_text(_OPTIONS, "B") == "B. dua"
    assert _find_option_text(_OPTIONS, "") is None
    assert _find_option_text([], "B") is None


def test_build_attempt_shape() -> None:  # KM-UNIT-044
    q = {"question_id": "q1", "type": "mcq"}
    attempt = _build_attempt(q, "jawaban siswa", 0.8, "Bagus.")
    for key in ("question_id", "student_answer", "score", "is_correct", "confidence"):
        assert key in attempt
    assert attempt["question_id"] == "q1"
    assert attempt["student_answer"] == "jawaban siswa"
    assert attempt["is_correct"] is True


@pytest.mark.parametrize(
    "score,expected",
    [(0.59, False), (0.60, True)],
)
def test_is_correct_threshold_0_6(score: float, expected: bool) -> None:  # KM-UNIT-045
    assert _build_attempt({}, "a", score, "")["is_correct"] is expected


async def test_emit_cumulative_is_mean() -> None:  # KM-UNIT-046
    state = {"quiz_attempts": [{"score": 1.0}, {"score": 0.0}]}
    out = await _emit(state, _build_attempt({}, "a", 0.5, "fb"))
    assert out["quiz_score"] == 0.5
    assert out["cumulative_quiz_score"] == pytest.approx(0.5)  # mean of [1, 0, 0.5]
    assert out["current_question_attempts"] == 1


async def test_empty_attempt_is_zero_and_safe() -> None:  # KM-UNIT-047
    out = await _empty_attempt({}, "no answer captured")
    assert out["quiz_score"] == 0.0
    assert out["next_action"] == "analyze_quiz"
    assert out["last_node"] == "scoring"
    assert out["current_question_attempts"] == 1
