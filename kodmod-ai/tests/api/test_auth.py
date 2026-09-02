"""Stage 4 §2 — JWT auth matrix on api/dependencies.py.

Spec: docs/testplan/04-api.md §2 (KM-API-010..021). Reference endpoint: GET /student/me.
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest

from config.settings import settings

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


def _encode(payload: dict, *, secret: str | None = None, alg: str | None = None) -> str:
    return pyjwt.encode(payload, secret or settings.JWT_SECRET, algorithm=alg or settings.JWT_ALG)


def _claims(sub, role="student", **extra):  # type: ignore[no-untyped-def]
    now = int(time.time())
    return {"sub": str(sub), "role": role, "iat": now, "exp": now + 3600, **extra}


async def test_km_api_010_valid_student_token(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    r = await client.get("/student/me", headers=auth_headers(tok))
    assert r.status_code == 200
    assert r.json()["id"] == str(st.id)


async def test_km_api_011_no_header(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/student/me")
    assert r.status_code == 401


async def test_km_api_012_wrong_scheme(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get("/student/me", headers={"Authorization": f"Token {tok}"})
    assert r.status_code == 401


@pytest.mark.known_bug(
    "#16 — _decode_jwt does uuid.UUID(sub) unguarded; a non-UUID sub raises ValueError -> 500"
)
async def test_km_api_013_sub_not_uuid(client) -> None:  # type: ignore[no-untyped-def]
    tok = _encode(_claims("not-a-uuid"))
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in {401, 422}


async def test_km_api_014_expired(client) -> None:  # type: ignore[no-untyped-def]
    now = int(time.time())
    tok = _encode(
        {"sub": str(uuid.uuid4()), "role": "student", "iat": now - 7200, "exp": now - 3600}
    )
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401
    assert "expired" in r.text.lower()


async def test_km_api_015_wrong_secret(client) -> None:  # type: ignore[no-untyped-def]
    tok = _encode(_claims(uuid.uuid4()), secret="a-different-secret-value-000000000000")
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


async def test_km_api_016_alg_none(client) -> None:  # type: ignore[no-untyped-def]
    tok = pyjwt.encode(_claims(uuid.uuid4()), key=None, algorithm="none")
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


async def test_km_api_017_teacher_token_on_student_endpoint(client, teacher_factory) -> None:  # type: ignore[no-untyped-def]
    _t, tok = await teacher_factory()
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


async def test_km_api_018_missing_sub_claim(client) -> None:  # type: ignore[no-untyped-def]
    now = int(time.time())
    tok = _encode({"role": "student", "iat": now, "exp": now + 3600})
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


async def test_km_api_019_valid_sub_no_student(client) -> None:  # type: ignore[no-untyped-def]
    tok = _encode(_claims(uuid.uuid4()))
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 404


async def test_km_api_020_tampered_payload(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    head, payload, sig = tok.split(".")
    # flip a character in the payload segment without re-signing
    tampered = f"{head}.{payload[:-2] + ('AA' if payload[-2:] != 'AA' else 'BB')}.{sig}"
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


async def test_km_api_021_current_teacher_rejects_student(
    client, student_factory, concept_ids
) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get(
        f"/analytics/classroom/{uuid.uuid4()}", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 403
