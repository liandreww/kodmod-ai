"""KM-UNIT-060..067 — conditional routers (graphs/main_graph.py).

The routers are pure functions of `state`. Importing graphs.main_graph pulls in
every node module; that's tolerated for now (see docs/testplan/01-unit.md
"Catatan implementasi" — extract to a routers module if it ever gets heavy).

Spec: docs/testplan/01-unit.md §5.
"""

from __future__ import annotations

import pytest

from graphs.main_graph import route_after_intent, route_after_scoring, route_after_student_model

pytestmark = pytest.mark.unit


def test_route_after_intent_tutoring() -> None:  # KM-UNIT-060
    assert route_after_intent({"intent": "tutoring"}) == "rag_retrieval"


@pytest.mark.parametrize("intent", ["quiz", "exercise_request"])
def test_route_after_intent_to_problem_generator(intent: str) -> None:  # KM-UNIT-061
    assert route_after_intent({"intent": intent}) == "problem_generator"


@pytest.mark.parametrize(
    "intent,expected",
    [
        ("analytics", "analytics"),
        ("repeat", "tutoring"),
        ("clarification", "tutoring"),
        ("stop", "end"),
        ("navigation", "tutoring"),  # unmapped → safe default
        ("unknown", "tutoring"),
    ],
)
def test_route_after_intent_table(intent: str, expected: str) -> None:  # KM-UNIT-062
    assert route_after_intent({"intent": intent}) == expected


def test_route_after_scoring_reads_settings_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    # KM-UNIT-063 — finding #12 fixed: route_after_scoring reads settings.QUIZ_PASS_THRESHOLD
    from config.settings import settings

    monkeypatch.setattr(settings, "QUIZ_PASS_THRESHOLD", 0.7)
    assert route_after_scoring({"quiz_score": 0.6}) == "tutoring"
    assert route_after_scoring({"quiz_score": 0.7}) == "update_student_model"


@pytest.mark.parametrize("score", [0.6, 0.85, 1.0])
def test_route_after_scoring_pass(score: float) -> None:  # KM-UNIT-064
    assert route_after_scoring({"quiz_score": score}) == "update_student_model"


def test_route_after_scoring_still_fails_below_max_attempts() -> None:
    # A low score alone stays in the remediation loop while attempts remain.
    state = {"quiz_score": 0.0, "current_question_attempts": 1}
    assert route_after_scoring(state) == "tutoring"


def test_route_after_scoring_forces_advance_at_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: a question the student can't clear must not trap the
    # quiz forever — once QUIZ_MAX_ATTEMPTS_PER_QUESTION is reached, the "pass"
    # branch fires regardless of score.
    from config.settings import settings

    monkeypatch.setattr(settings, "QUIZ_MAX_ATTEMPTS_PER_QUESTION", 2)
    state = {"quiz_score": 0.0, "current_question_attempts": 2}
    assert route_after_scoring(state) == "update_student_model"


def test_route_after_student_model_more_questions_left() -> None:  # KM-UNIT-065
    # `current_question_index` has already been advanced by update_student_model;
    # it still points at a valid question → loop back to quiz_ask so the next
    # question is spoken within this same turn.
    state = {"quiz_questions": [{}, {}, {}], "current_question_index": 1}
    assert route_after_student_model(state) == "quiz_ask"


def test_route_after_student_model_questions_exhausted() -> None:  # KM-UNIT-066
    state = {"quiz_questions": [{}, {}], "current_question_index": 2}
    assert route_after_student_model(state) == "quiz_analyzer"


def test_routers_tolerate_partial_state() -> None:  # KM-UNIT-067
    assert route_after_intent({}) == "tutoring"
    assert route_after_scoring({}) == "tutoring"
    # no KeyError on missing quiz_questions
    assert route_after_student_model({}) == "quiz_analyzer"
