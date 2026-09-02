"""Stage 4 §9 — /analytics endpoints.

Spec: docs/testplan/04-api.md §9 (KM-API-090..096).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def test_km_api_090_student_analytics_self(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.get(f"/analytics/student/{st.id}", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["student_id"] == str(st.id)
    assert "overall_mastery" in body


async def test_km_api_091_student_analytics_idor(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _a, tok = await student_factory()
    r = await client.get(f"/analytics/student/{uuid.uuid4()}", headers=auth_headers(tok))
    assert r.status_code == 403


async def test_km_api_092_window_param(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    for w in ("today", "week", "month", "all"):
        r = await client.get(
            f"/analytics/student/{st.id}", params={"window": w}, headers=auth_headers(tok)
        )
        assert r.status_code == 200
    bad = await client.get(
        f"/analytics/student/{st.id}", params={"window": "xyz"}, headers=auth_headers(tok)
    )
    assert bad.status_code == 422


async def test_km_api_093_student_spoken(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.get(f"/analytics/student/{st.id}/spoken", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["spoken"], str) and body["spoken"].strip()
    assert "rollup" in body


@pytest.mark.known_bug(
    "#20 — GET /analytics/classroom/{id} runs ClassroomAggregator which queries the missing "
    "classroom_enrollment table"
)
async def test_km_api_094_classroom_analytics(client, teacher_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    teacher, tok = await teacher_factory()
    from database.models import Classroom
    from database.session import async_session, init_db

    await init_db()
    cid = uuid.uuid4()
    async with async_session() as s:
        s.add(Classroom(id=cid, name="Kelas Uji", teacher_id=teacher.id))
    try:
        r = await client.get(f"/analytics/classroom/{cid}", headers=auth_headers(tok))
        assert r.status_code == 200
        assert "n_students" in r.json()
    finally:
        async with async_session() as s:
            from sqlalchemy import text

            await s.execute(text("DELETE FROM classrooms WHERE id = :id"), {"id": str(cid)})


@pytest.mark.known_bug(
    "#20 — classroom alerts depends on the same missing classroom_enrollment table"
)
async def test_km_api_095_classroom_alerts(client, teacher_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _t, tok = await teacher_factory()
    r = await client.get(f"/analytics/classroom/{uuid.uuid4()}/alerts", headers=auth_headers(tok))
    assert r.status_code == 200
    assert {"alerts", "per_student", "headline"} <= set(r.json())


async def test_km_api_096_classroom_endpoint_rejects_student(
    client, student_factory, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get(f"/analytics/classroom/{uuid.uuid4()}", headers=auth_headers(tok))
    assert r.status_code == 403
