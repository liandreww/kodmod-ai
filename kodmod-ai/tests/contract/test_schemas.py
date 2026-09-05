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
# KM-CONTRACT-001 / 002 — RegisterRequest
# --------------------------------------------------------------------------- #
def test_km_contract_001_register_request_valid() -> None:
    from models.user import RegisterRequest

    r = RegisterRequest(
        username="Budi.S",
        password="rahasia-panjang",
        full_name="Budi Santoso",
        role="student",
        invitation_code="abc123",
    )
    # Usernames are compared case-insensitively, codes are shown in upper case.
    assert r.username == "budi.s"
    assert r.invitation_code == "ABC123"
    assert r.preferred_language == "id"


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "admin"),  # admin is never self-serve
        ("username", "ab"),  # too short
        ("username", "budi santoso"),  # spaces are not allowed
        ("password", "short"),  # below the minimum length
    ],
)
def test_km_contract_002_register_request_rejects(field: str, value: str) -> None:
    from models.user import RegisterRequest

    payload = {
        "username": "budi",
        "password": "rahasia-panjang",
        "full_name": "Budi",
        "role": "student",
        "invitation_code": "ABC123",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        RegisterRequest(**payload)


# --------------------------------------------------------------------------- #
# KM-CONTRACT-003 / 004 — UserOut never leaks credentials
# --------------------------------------------------------------------------- #
def _user_row(**over: object) -> SimpleNamespace:
    now = datetime.now(UTC)
    base = dict(
        id=uuid.uuid4(),
        username="budi",
        password_hash="$2b$12$notarealhash",
        role="student",
        full_name="Budi Santoso",
        is_active=True,
        grade_level=None,
        preferred_language="id",
        accessibility_profile="blind",
        created_at=now,
        last_login_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_km_contract_003_user_out_from_attributes() -> None:
    from models.user import UserOut

    out = UserOut.model_validate(_user_row())
    assert isinstance(out.id, uuid.UUID)
    assert isinstance(out.created_at, datetime)
    assert out.role == "student"


def test_km_contract_004_user_out_excludes_password_hash() -> None:
    """The single most important schema guarantee in the codebase."""
    from models.user import UserOut

    dumped = UserOut.model_validate(_user_row()).model_dump()
    assert "password_hash" not in dumped
    assert not any("password" in key for key in dumped)


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
    }
    r = QuizSubmitRequest(quiz_session_id=uuid.uuid4(), question_id="q1", student_answer="A")
    assert r.response_latency_ms is None


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


def test_km_contract_013_no_schema_exposes_audio_fields() -> None:
    """Speech lives in the browser: no API schema should still carry audio URLs."""
    import models

    offenders: list[str] = []
    for mod_info in pkgutil.iter_modules(models.__path__):
        module = importlib.import_module(f"models.{mod_info.name}")
        for name, obj in vars(module).items():
            if not (inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel):
                continue
            offenders += [
                f"{name}.{field}"
                for field in obj.model_fields
                if any(marker in field for marker in ("audio_url", "audio_uri", "transcrib"))
            ]
    assert not offenders, f"audio-era fields still in the API schema: {offenders}"


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
        "respond",
        "end",
        "interrupt_human",
    )
