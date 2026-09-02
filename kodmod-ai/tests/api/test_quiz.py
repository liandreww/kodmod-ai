"""Stage 4 §7 — /quiz endpoints.

Spec: docs/testplan/04-api.md §7 (KM-API-070..075). Whole group is a known-bug
backlog until #1 (Student.profile), #5 (field mismatch), #6, #11 are fixed.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


@pytest.mark.known_bug(
    "#1 / #5 — POST /quiz/start does state['learning_profile']=student.profile (Student has no "
    ".profile) -> 500; response also built with fields QuizStartResponse doesn't declare"
)
async def test_km_api_070_quiz_start(client, student_factory, concept_ids, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.post(
        "/quiz/start",
        headers=auth_headers(tok),
        json={
            "student_id": str(st.id),
            "concept_id": concept_ids["pecahan"],
            "n_questions": 3,
            "difficulty": "easy",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert {"quiz_session_id", "first_question", "total_questions"} <= set(body)


@pytest.mark.known_bug(
    "#6 — _load_mastery previously chained coroutines; verify start path no longer 500s on it"
)
async def test_km_api_071_quiz_start_load_mastery_ok(
    client, student_factory, concept_ids, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.post(
        "/quiz/start",
        headers=auth_headers(tok),
        json={"student_id": str(st.id), "concept_id": concept_ids["pecahan"], "n_questions": 2},
    )
    assert r.status_code != 500


@pytest.mark.known_bug(
    "#5 — POST /quiz/submit reads body.session_id / body.answer_text; QuizSubmitRequest has "
    "quiz_session_id / student_answer -> AttributeError 500"
)
async def test_km_api_072_quiz_submit(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/quiz/submit",
        headers=auth_headers(tok),
        json={"quiz_session_id": str(uuid.uuid4()), "question_id": "q1", "student_answer": "A"},
    )
    assert r.status_code == 200
    assert {"score", "is_correct", "feedback", "quiz_complete", "cumulative_score"} <= set(r.json())


@pytest.mark.known_bug("#5 / #11 — final submit should return quiz_complete=True + final_summary")
async def test_km_api_073_quiz_submit_completes(
    client, student_factory, concept_ids, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    start = await client.post(
        "/quiz/start",
        headers=auth_headers(tok),
        json={"student_id": str(st.id), "concept_id": concept_ids["pecahan"], "n_questions": 1},
    )
    assert start.status_code == 200
    sess = start.json()["quiz_session_id"]
    sub = await client.post(
        "/quiz/submit",
        headers=auth_headers(tok),
        json={"quiz_session_id": sess, "question_id": "q1", "student_answer": "A"},
    )
    assert sub.json()["quiz_complete"] is True
    assert sub.json()["final_summary"]


@pytest.mark.known_bug("#14 — POST /quiz/start should reject a body.student_id != token student")
async def test_km_api_074_quiz_start_idor(
    client, student_factory, concept_ids, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/quiz/start",
        headers=auth_headers(tok),
        json={
            "student_id": str(uuid.uuid4()),
            "concept_id": concept_ids["pecahan"],
            "n_questions": 2,
        },
    )
    assert r.status_code == 403
