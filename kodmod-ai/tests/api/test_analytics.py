"""Stage 4 §9 — /analytics endpoints.

Spec: docs/testplan/04-api.md §9 (KM-API-090..097).

There are no classrooms: a teacher sees every student, and the cohort rollup is
what the teacher dashboard reads.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def test_km_api_090_own_analytics(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.get("/analytics/me", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["student_id"] == str(st.id)
    assert "overall_mastery" in body


async def test_km_api_091_student_cannot_read_another_student(  # type: ignore[no-untyped-def]
    client, student_factory, auth_headers
) -> None:
    _a, tok = await student_factory()
    r = await client.get(f"/analytics/student/{uuid.uuid4()}", headers=auth_headers(tok))
    assert r.status_code == 403


async def test_km_api_092_window_param(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    for w in ("today", "week", "month", "all"):
        r = await client.get("/analytics/me", params={"window": w}, headers=auth_headers(tok))
        assert r.status_code == 200
    bad = await client.get("/analytics/me", params={"window": "xyz"}, headers=auth_headers(tok))
    assert bad.status_code == 422


async def test_km_api_093_spoken_summary(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get("/analytics/me/spoken", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["spoken"], str) and body["spoken"].strip()
    assert "summary" in body


async def test_km_api_094_cohort_analytics(client, teacher_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _teacher, tok = await teacher_factory()
    r = await client.get("/analytics/cohort", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert "n_students" in body
    assert isinstance(body["students"], list)


async def test_km_api_095_cohort_alerts(client, teacher_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _teacher, tok = await teacher_factory()
    r = await client.get("/analytics/cohort/alerts", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["alerts"], list)
    assert "summary" in body


async def test_km_api_096_cohort_rejects_student(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get("/analytics/cohort", headers=auth_headers(tok))
    assert r.status_code == 403


async def test_km_api_097_teacher_may_read_any_student(  # type: ignore[no-untyped-def]
    client, student_factory, teacher_factory, auth_headers
) -> None:
    """The teacher dashboard depends on this; the student route must allow it."""
    student, _ = await student_factory()
    _teacher, teacher_token = await teacher_factory()
    r = await client.get(f"/analytics/student/{student.id}", headers=auth_headers(teacher_token))
    assert r.status_code == 200
    assert r.json()["student_id"] == str(student.id)
