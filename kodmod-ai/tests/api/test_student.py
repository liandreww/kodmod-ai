"""Stage 4 §4 — /student endpoints.

Spec: docs/testplan/04-api.md §4 (KM-API-040..045).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def test_km_api_040_create_student(client, db_cleanup) -> None:  # type: ignore[no-untyped-def]
    r = await client.post(
        "/student",
        json={
            "full_name": "Ani Baru",
            "preferred_language": "id",
            "accessibility_profile": "blind",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["full_name"] == "Ani Baru"
    assert "id" in body and "created_at" in body
    db_cleanup.append(("students", body["id"]))


@pytest.mark.known_bug(
    'new finding (Schemathesis) — POST /student with a duplicate email (incl. "") raises an '
    "unhandled IntegrityError -> 500; should be 409/422"
)
async def test_km_api_040b_duplicate_email(client, db_cleanup) -> None:  # type: ignore[no-untyped-def]
    email = f"dup-{uuid.uuid4().hex[:10]}@example.test"
    first = await client.post("/student", json={"full_name": "A", "email": email})
    assert first.status_code == 201
    db_cleanup.append(("students", first.json()["id"]))
    second = await client.post("/student", json={"full_name": "B", "email": email})
    assert second.status_code in {409, 422}


async def test_km_api_041_create_student_invalid(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.post("/student", json={"full_name": 123, "preferred_language": []})
    assert r.status_code == 422


async def test_km_api_042_student_me(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory(full_name="Me Myself")
    r = await client.get("/student/me", headers=auth_headers(tok))
    assert r.status_code == 200
    assert r.json()["full_name"] == "Me Myself"


async def test_km_api_043_student_profile(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.get(f"/student/{st.id}/profile", headers=auth_headers(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(st.id)
    assert "overall_mastery" in body
    assert body["strong_concepts"] == []  # hardcoded in handler (documented)


async def test_km_api_044_student_profile_not_found(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    # Own token, but a random target id: the owner check fires before the lookup.
    r = await client.get(f"/student/{uuid.uuid4()}/profile", headers=auth_headers(tok))
    assert r.status_code in {403, 404}


@pytest.mark.known_bug(
    "#14 — GET /student/{id}/profile has no auth: student A can read student B's profile"
)
async def test_km_api_045_student_profile_idor(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    victim, _v = await student_factory(full_name="Korban")
    _attacker, atk_tok = await student_factory(full_name="Penyerang")
    r = await client.get(f"/student/{victim.id}/profile", headers=auth_headers(atk_tok))
    assert r.status_code in {401, 403}
