"""KM-UNIT-060..067 — conditional routers (graphs/main_graph.py).

The routers are pure functions of `state`. Importing graphs.main_graph pulls in
every node module; that's tolerated for now (see docs/testplan/01-unit.md
"Catatan implementasi" — extract to a routers module if it ever gets heavy).

Spec: docs/testplan/01-unit.md §5.
"""

from __future__ import annotations

import pytest

from graphs.main_graph import route_after_analyzer, route_after_intent, route_after_scoring

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
        ("stop", "end_speak"),
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


def test_route_after_analyzer_more_questions_left() -> None:  # KM-UNIT-065
    # `current_question_index` has already been advanced by update_student_model;
    # it still points at a valid question → end this turn (next question is asked
    # when the student's following utterance re-enters the graph).
    state = {"quiz_questions": [{}, {}, {}], "current_question_index": 1}
    assert route_after_analyzer(state) == "end"


def test_route_after_analyzer_questions_exhausted() -> None:  # KM-UNIT-066
    state = {"quiz_questions": [{}, {}], "current_question_index": 2}
    assert route_after_analyzer(state) == "analytics"


def test_routers_tolerate_partial_state() -> None:  # KM-UNIT-067
    assert route_after_intent({}) == "tutoring"
    assert route_after_scoring({}) == "tutoring"
    assert route_after_analyzer({}) == "analytics"  # no KeyError on missing quiz_questions
