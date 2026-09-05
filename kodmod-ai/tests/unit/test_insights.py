"""KM-UNIT-110..123 — rule-based insight generation.

Covers analytics/insights.py (student/teacher/cohort rule engines + the
`use_llm` switch) and analytics/aggregator.py::_window_start.

Spec: docs/testplan/01-unit.md §8.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from analytics.aggregator import _window_start
from analytics.insights import (
    _format_concept_list,
    _pct,
    generate_cohort_alerts,
    generate_insights,
    generate_student_spoken_summary,
    generate_teacher_summary,
)

pytestmark = pytest.mark.unit


class _GetterSpy:
    """Records how analytics.insights.get_recommendation_llm gets called."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args: object, **kwargs: object):
        self.calls.append((args, kwargs))
        from tests._fakes.fake_chat import make_fake_chat

        return make_fake_chat("recommendation")


# --------------------------------------------------------------- helpers --
def test_pct() -> None:  # KM-UNIT-110
    assert _pct(0.42) == "42 persen"


def test_format_concept_list_caps_at_n() -> None:  # KM-UNIT-111
    items = [{"concept_name": n} for n in ("Alfa", "Beta", "Gamma", "Delta", "Epsilon")]
    out = _format_concept_list(items, n=3)
    assert "Alfa" in out and "Gamma" in out
    assert "Delta" not in out and "Epsilon" not in out


def _days_ago(dt: datetime) -> float:
    return (datetime.now(UTC) - dt).total_seconds() / 86400


@pytest.mark.parametrize(
    "window,check",
    [
        ("today", lambda d: d is not None and d.hour == 0 and d.minute == 0 and d.tzinfo is UTC),
        ("week", lambda d: d is not None and abs(_days_ago(d) - 7) <= 1),
        ("month", lambda d: d is not None and abs(_days_ago(d) - 30) <= 1),
        ("all", lambda d: d is None),
    ],
)
def test_window_start(window: str, check) -> None:  # KM-UNIT-112
    assert check(_window_start(window))  # type: ignore[arg-type]


# ------------------------------------------------- student-facing summary --
def test_student_summary_error_is_graceful() -> None:  # KM-UNIT-113
    out = generate_student_spoken_summary({"error": "student_not_found"})
    assert isinstance(out, str) and out
    assert "Maaf" in out


def test_student_summary_zero_sessions() -> None:  # KM-UNIT-114
    out = generate_student_spoken_summary({"n_sessions": 0, "student_name": "Budi"})
    assert "belum belajar" in out


@pytest.mark.parametrize(
    "accuracy,phrase",
    [
        (0.9, "sangat baik"),
        (0.65, "Teruskan latihan"),
        (0.3, "Jangan khawatir"),
    ],
)
def test_student_summary_accuracy_tiers(accuracy: float, phrase: str) -> None:  # KM-UNIT-115
    out = generate_student_spoken_summary(
        {"n_sessions": 3, "quiz_accuracy": accuracy, "overall_mastery": 0.5}
    )
    assert phrase in out


# ------------------------------------------------- teacher-facing summary --
def test_teacher_alert_low_accuracy() -> None:  # KM-UNIT-116
    out = generate_teacher_summary({"n_quiz_attempts": 3, "quiz_accuracy": 0.4})
    assert any(a["level"] == "warning" for a in out["alerts"])


def test_teacher_alert_low_engagement() -> None:  # KM-UNIT-117
    out = generate_teacher_summary({"engagement_index": 0.1, "n_sessions": 1})
    assert any(a["level"] == "warning" for a in out["alerts"])


def test_teacher_alert_open_misconceptions() -> None:  # KM-UNIT-118
    out = generate_teacher_summary({"open_misconceptions": [{"description": "salah kali silang"}]})
    assert any(a["level"] == "info" for a in out["alerts"])


def test_teacher_alert_high_mastery() -> None:  # KM-UNIT-119
    # No warning/info alert conditions met → the "strong mastery" success alert fires.
    out = generate_teacher_summary(
        {"overall_mastery": 0.9, "engagement_index": 0.5, "n_sessions": 5}
    )
    assert any(a["level"] == "success" for a in out["alerts"])


# --------------------------------------------------- cohort-level alerts --
def test_cohort_alert_weak_concept() -> None:  # KM-UNIT-120
    out = generate_cohort_alerts(
        {
            "cohort_weak_concepts": [
                {"concept_name": "Pecahan", "avg_mastery": 0.4, "n_students": 10}
            ]
        }
    )
    assert any(a["level"] == "warning" for a in out)


def test_cohort_alert_low_engagement() -> None:  # KM-UNIT-121
    out = generate_cohort_alerts({"avg_engagement_index": 0.2, "cohort_weak_concepts": []})
    assert any(a["level"] == "info" for a in out)


# ----------------------------------------------------------- LLM switch --
async def test_generate_insights_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:  # KM-UNIT-122
    spy = _GetterSpy()
    monkeypatch.setattr("analytics.insights.get_recommendation_llm", spy)
    out = await generate_insights(
        {"n_sessions": 2, "quiz_accuracy": 0.7, "overall_mastery": 0.6, "student_name": "Budi"},
        use_llm=False,
    )
    assert set(out) == {"spoken", "structured"}
    assert spy.calls == []  # LLM never touched


async def test_generate_insights_llm_getter_takes_no_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # KM-UNIT-123
    # finding #8 fixed: generate_insights calls the role getter with no arguments.
    spy = _GetterSpy()
    monkeypatch.setattr("analytics.insights.get_recommendation_llm", spy)
    await generate_insights(
        {"n_sessions": 2, "quiz_accuracy": 0.7, "overall_mastery": 0.6, "student_name": "Budi"},
        use_llm=True,
    )
    assert spy.calls == [((), {})]
