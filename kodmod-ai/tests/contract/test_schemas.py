"""Stage 2 — Contract / Schema: Pydantic models in ``models/*``.

Spec: docs/testplan/02-contract.md §1 (KM-CONTRACT-001..015).

No I/O — pure schema construction and introspection. Where a model is looser
than the spec's target contract the test asserts the TARGET and carries
``@pytest.mark.known_bug`` (policy 2026-09-02: no more xfail).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

pytestmark = pytest.mark.contract


# --------------------------------------------------------------------------- #
# KM-CONTRACT-001 / 002 — StudentCreate
# --------------------------------------------------------------------------- #
def test_km_contract_001_student_create_valid() -> None:
    from models.student import StudentCreate

    s = StudentCreate(full_name="Siswa Uji")
    assert s.full_name == "Siswa Uji"
    assert s.accessibility_profile == "blind"
    assert s.preferred_language == "id"
    assert s.voice_settings == {}  # default_factory=dict


@pytest.mark.known_bug(
    "schema: StudentBase.preferred_language is plain `str`, not Literal['id','en'] — "
    "invalid language codes are silently accepted"
)
def test_km_contract_002_student_create_rejects_bad_language() -> None:
    from models.student import StudentCreate

    with pytest.raises(ValidationError):
        StudentCreate(full_name="X", preferred_language="fr")


# --------------------------------------------------------------------------- #
# KM-CONTRACT-003 / 004 — StudentOut / StudentProfileOut from ORM attrs
# --------------------------------------------------------------------------- #
def _student_row(**over: object) -> SimpleNamespace:
    now = datetime.now(UTC)
    base = dict(
        id=uuid.uuid4(),
        full_name="Siswa Uji",
        email=None,
        grade_level=None,
        accessibility_profile="blind",
        preferred_language="id",
        voice_settings={},
        created_at=now,
        updated_at=now,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_km_contract_003_student_out_from_attributes() -> None:
    from models.student import StudentOut

    out = StudentOut.model_validate(_student_row())
    assert isinstance(out.id, uuid.UUID)
    assert isinstance(out.created_at, datetime)
    assert isinstance(out.updated_at, datetime)


def test_km_contract_004_student_profile_out_shape() -> None:
    from models.student import StudentProfileOut

    out = StudentProfileOut.model_validate(
        _student_row(),
    )
    # extended aggregate fields default cleanly
    assert out.overall_mastery == 0.0
    assert out.weak_concepts == []
    assert out.strong_concepts == []
    assert out.streak_days == 0
    assert out.last_active_at is None

    filled = StudentProfileOut(
        **_student_row().__dict__,
        overall_mastery=0.5,
        weak_concepts=["pecahan"],
        strong_concepts=["tata-surya"],
        streak_days=3,
        last_active_at=datetime.now(UTC),
    )
    assert filled.weak_concepts == ["pecahan"]


# --------------------------------------------------------------------------- #
# KM-CONTRACT-005..008 — Quiz request/response models
# --------------------------------------------------------------------------- #
def test_km_contract_005_quiz_start_request_bounds() -> None:
    from models.quiz import QuizStartRequest

    sid = uuid.uuid4()
    ok = QuizStartRequest(student_id=sid, n_questions=1, difficulty="easy")
    assert ok.n_questions == 1
    assert QuizStartRequest(student_id=sid, n_questions=20).n_questions == 20

    for bad in (0, 21, -1):
        with pytest.raises(ValidationError):
            QuizStartRequest(student_id=sid, n_questions=bad)

    with pytest.raises(ValidationError):
        QuizStartRequest(student_id=sid, difficulty="trivial")


def test_km_contract_006_quiz_start_response_shape() -> None:
    from models.quiz import QuizQuestionOut, QuizStartResponse

    q = QuizQuestionOut(
        question_id="q1",
        order_index=0,
        question="Berapa satu per dua ditambah satu per dua?",
        question_type="mcq",
        options=["A", "B", "C", "D"],
    )
    resp = QuizStartResponse(quiz_session_id=uuid.uuid4(), first_question=q, total_questions=3)
    assert set(QuizStartResponse.model_fields) == {
        "quiz_session_id",
        "first_question",
        "total_questions",
    }
    assert resp.total_questions == 3


def test_km_contract_007_quiz_submit_request_field_names() -> None:
    from models.quiz import QuizSubmitRequest

    assert set(QuizSubmitRequest.model_fields) == {
        "quiz_session_id",
        "question_id",
        "student_answer",
        "response_latency_ms",
        "transcribed_from_audio",
    }
    r = QuizSubmitRequest(quiz_session_id=uuid.uuid4(), question_id="q1", student_answer="A")
    assert r.response_latency_ms is None
    assert r.transcribed_from_audio is False


def test_km_contract_008_quiz_submit_response_defaults_and_bounds() -> None:
    from models.quiz import QuizSubmitResponse

    r = QuizSubmitResponse(score=0.5, is_correct=True, feedback="Bagus.")
    assert r.quiz_complete is False
    assert r.cumulative_score == 0.0
    assert r.next_question is None

    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            QuizSubmitResponse(score=bad, is_correct=False, feedback="x")


# --------------------------------------------------------------------------- #
# KM-CONTRACT-009..013 — content / exercise / session models
# --------------------------------------------------------------------------- #
def test_km_contract_009_content_retrieve_request_bounds() -> None:
    from models.content import ContentRetrieveRequest

    d = ContentRetrieveRequest(query="pecahan")
    assert d.top_k == 5
    assert d.language == "id"
    for bad in (0, 21):
        with pytest.raises(ValidationError):
            ContentRetrieveRequest(query="x", top_k=bad)


def test_km_contract_010_content_retrieve_response() -> None:
    from models.content import ContentRetrieveResponse

    r = ContentRetrieveResponse(chunks=[{"id": "1", "text": "t"}], query="pecahan")
    assert r.chunks[0]["text"] == "t"


def test_km_contract_011_exercise_generate_round_trip() -> None:
    from models.content import ExerciseGenerateRequest, ExerciseGenerateResponse

    req = ExerciseGenerateRequest(student_id=uuid.uuid4(), n_questions=3, difficulty="medium")
    assert req.n_questions == 3
    resp = ExerciseGenerateResponse(exercises=[{"q": "1+1?"}], generated_at=datetime.now(UTC))
    assert resp.exercises[0]["q"] == "1+1?"


def test_km_contract_012_orm_out_models_from_attributes() -> None:
    from models.content import ConceptOut, ExerciseOut, LessonOut

    concept = ConceptOut.model_validate(
        SimpleNamespace(
            id=uuid.uuid4(),
            name="Pecahan",
            slug="pecahan",
            description=None,
            difficulty_level="easy",
        )
    )
    assert concept.slug == "pecahan"
    lesson = LessonOut.model_validate(
        SimpleNamespace(
            id=uuid.uuid4(),
            concept_id=concept.id,
            title="Bab 1",
            body_md="isi",
            audio_friendly_summary=None,
            estimated_minutes=8,
        )
    )
    assert lesson.estimated_minutes == 8
    ex = ExerciseOut.model_validate(
        SimpleNamespace(
            id=uuid.uuid4(),
            concept_id=concept.id,
            question="1+1?",
            question_type="mcq",
            options=["2", "3"],
            difficulty="easy",
        )
    )
    assert ex.options == ["2", "3"]


def test_km_contract_013_session_models_are_dead_but_valid() -> None:
    # models/session.py is not wired to any route (documented dead schema in
    # traceability.md) — still must round-trip so it doesn't rot silently.
    from models.session import (
        SessionOut,
        SessionStartRequest,
        VoiceChatRequest,
        VoiceChatResponse,
    )

    sid = uuid.uuid4()
    assert SessionStartRequest(student_id=sid).mode == "tutoring"
    SessionOut.model_validate(
        SimpleNamespace(
            id=sid,
            student_id=sid,
            started_at=datetime.now(UTC),
            ended_at=None,
            mode="quiz",
            summary=None,
        )
    )
    assert VoiceChatRequest(student_id=sid, text="halo").language == "id"
    assert VoiceChatResponse(session_id=sid, intent="tutoring", response_text="hai").latency_ms == 0


# --------------------------------------------------------------------------- #
# KM-CONTRACT-014 — every model class serialises its JSON schema
# --------------------------------------------------------------------------- #
def _iter_model_classes():
    import models as models_pkg

    seen: set[type] = set()
    for mod in pkgutil.iter_modules(models_pkg.__path__, "models."):
        m = importlib.import_module(mod.name)
        for _name, obj in inspect.getmembers(m, inspect.isclass):
            if issubclass(obj, BaseModel) and obj is not BaseModel and obj.__module__ == m.__name__:
                if obj not in seen:
                    seen.add(obj)
                    yield obj


def test_km_contract_014_all_models_json_schema() -> None:
    classes = list(_iter_model_classes())
    assert classes, "no pydantic models discovered under models/"
    for cls in classes:
        schema = cls.model_json_schema()
        assert isinstance(schema, dict) and schema.get("type") in {"object", None}


# --------------------------------------------------------------------------- #
# KM-CONTRACT-015 — graph-state Literals match a frozen snapshot
# --------------------------------------------------------------------------- #
def test_km_contract_015_state_literals_snapshot() -> None:
    from typing import get_args

    from graphs import state as st

    assert get_args(st.Intent) == (
        "tutoring",
        "quiz",
        "analytics",
        "clarification",
        "exercise_request",
        "help",
        "navigation",
        "repeat",
        "stop",
        "unknown",
    )
    assert get_args(st.DifficultyLevel) == ("beginner", "easy", "medium", "hard", "expert")
    assert get_args(st.EmotionalState) == (
        "neutral",
        "engaged",
        "confused",
        "frustrated",
        "fatigued",
        "motivated",
    )
    assert get_args(st.NextAction) == (
        "route_intent",
        "tutor",
        "generate_quiz",
        "ask_question",
        "score_answer",
        "analyze_quiz",
        "update_student_model",
        "generate_analytics",
        "recommend",
        "accessibility_polish",
        "speak",
        "end",
        "interrupt_human",
    )
