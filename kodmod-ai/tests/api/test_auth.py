"""Stage 4 §2 — authentication and the role gate, over real HTTP.

Spec: docs/testplan/04-api.md §2 (KM-API-010..028).

The reference endpoint for token handling is GET /auth/me: it needs nothing but
a valid token, so a failure there is unambiguously about authentication.
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest

from config.settings import settings

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

ME = "/auth/me"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Token handling
# --------------------------------------------------------------------------- #
async def test_km_api_010_valid_token_is_accepted(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    student, token = await student_factory()
    r = await client.get(ME, headers=_bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(student.id)
    assert body["role"] == "student"


async def test_km_api_011_response_never_carries_the_hash(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    r = await client.get(ME, headers=_bearer(token))
    assert r.status_code == 200
    assert "password_hash" not in r.text


async def test_km_api_012_missing_header_is_401(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get(ME)).status_code == 401


@pytest.mark.parametrize("scheme", ["Token", "Basic", "bearer_no_space"])
async def test_km_api_013_wrong_scheme_is_401(client, student_factory, scheme: str) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    header = f"{scheme} {token}" if scheme != "bearer_no_space" else f"Bearer{token}"
    r = await client.get(ME, headers={"Authorization": header})
    assert r.status_code == 401


async def test_km_api_014_garbage_token_is_401(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get(ME, headers=_bearer("not.a.jwt"))).status_code == 401


async def test_km_api_015_expired_token_is_401(client, student_factory, make_token) -> None:  # type: ignore[no-untyped-def]
    student, _ = await student_factory()
    expired = make_token(student.id, "student", ttl_s=-60)
    assert (await client.get(ME, headers=_bearer(expired))).status_code == 401


async def test_km_api_016_foreign_secret_is_401(client, student_factory, make_token) -> None:  # type: ignore[no-untyped-def]
    student, _ = await student_factory()
    forged = make_token(student.id, "student", secret="a-different-secret-entirely")
    assert (await client.get(ME, headers=_bearer(forged))).status_code == 401


async def test_km_api_017_alg_none_token_is_rejected(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    """The classic JWT bypass: an unsigned token claiming to be valid."""
    student, _ = await student_factory()
    now = int(time.time())
    unsigned = pyjwt.encode(
        {"sub": str(student.id), "role": "student", "iat": now, "exp": now + 3600},
        key="",
        algorithm="none",
    )
    assert (await client.get(ME, headers=_bearer(unsigned))).status_code == 401


async def test_km_api_018_tampered_payload_is_401(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    head, _payload, sig = token.split(".")
    other = pyjwt.encode({"sub": str(uuid.uuid4()), "role": "admin"}, "x", algorithm="HS256")
    tampered = f"{head}.{other.split('.')[1]}.{sig}"
    assert (await client.get(ME, headers=_bearer(tampered))).status_code == 401


async def test_km_api_019_token_for_a_deleted_account_is_401(client, make_token) -> None:  # type: ignore[no-untyped-def]
    """A well-formed token naming nobody must not authenticate."""
    orphan = make_token(uuid.uuid4(), "student")
    assert (await client.get(ME, headers=_bearer(orphan))).status_code == 401


async def test_km_api_020_token_role_must_match_the_row(
    client, student_factory, make_token
) -> None:  # type: ignore[no-untyped-def]
    """Claiming a role in the token does not grant it: the account row decides."""
    student, _ = await student_factory()
    escalated = make_token(student.id, "admin")
    assert (await client.get(ME, headers=_bearer(escalated))).status_code == 401


# --------------------------------------------------------------------------- #
# Role gate
# --------------------------------------------------------------------------- #
async def test_km_api_021_student_cannot_reach_teacher_routes(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    assert (await client.get("/teacher/students", headers=_bearer(token))).status_code == 403


async def test_km_api_022_teacher_cannot_reach_admin_routes(client, teacher_factory) -> None:  # type: ignore[no-untyped-def]
    _teacher, token = await teacher_factory()
    assert (await client.get("/admin/users", headers=_bearer(token))).status_code == 403


async def test_km_api_023_admin_cannot_reach_student_routes(client, admin_factory) -> None:  # type: ignore[no-untyped-def]
    """Role gates cut both ways: an admin is not a learner."""
    _admin, token = await admin_factory()
    assert (await client.get("/student/me/profile", headers=_bearer(token))).status_code == 403


async def test_km_api_024_disabled_account_is_locked_out(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    """Disabling an account takes effect at once, not when the token expires."""
    from sqlalchemy import text

    from database.session import async_session

    student, token = await student_factory()
    assert (await client.get(ME, headers=_bearer(token))).status_code == 200

    async with async_session() as s:
        await s.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": str(student.id)}
        )

    assert (await client.get(ME, headers=_bearer(token))).status_code == 403


# --------------------------------------------------------------------------- #
# Register and login, the whole front door
# --------------------------------------------------------------------------- #
async def test_km_api_025_register_then_login(client, admin_factory) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session

    _admin, admin_token = await admin_factory()

    created = await client.post(
        "/admin/invitations", json={"label": "uji", "max_uses": 1}, headers=_bearer(admin_token)
    )
    assert created.status_code == 201, created.text
    code = created.json()["code"]

    username = f"pendaftar-{uuid.uuid4().hex[:8]}"
    password = "kata-sandi-uji-123"
    try:
        registered = await client.post(
            "/auth/register",
            json={
                "username": username,
                "password": password,
                "full_name": "Pendaftar Uji",
                "role": "student",
                "invitation_code": code,
            },
        )
        assert registered.status_code == 201, registered.text
        assert registered.json()["user"]["role"] == "student"

        # Single-use code: a second registration must be refused.
        again = await client.post(
            "/auth/register",
            json={
                "username": f"{username}-2",
                "password": password,
                "full_name": "Pendaftar Kedua",
                "role": "student",
                "invitation_code": code,
            },
        )
        assert again.status_code == 400

        ok = await client.post("/auth/login", json={"username": username, "password": password})
        assert ok.status_code == 200
        assert ok.json()["token_type"] == "bearer"

        bad = await client.post(
            "/auth/login", json={"username": username, "password": "bukan-sandinya"}
        )
        assert bad.status_code == 401
    finally:
        async with async_session() as s:
            await s.execute(text("DELETE FROM users WHERE username = :u"), {"u": username})
            await s.execute(text("DELETE FROM invitation_codes WHERE code = :c"), {"c": code})


async def test_km_api_026_registration_requires_a_valid_code(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.post(
        "/auth/register",
        json={
            "username": f"tanpa-kode-{uuid.uuid4().hex[:6]}",
            "password": "kata-sandi-uji-123",
            "full_name": "Tanpa Kode",
            "role": "student",
            "invitation_code": "TIDAKADA",
        },
    )
    assert r.status_code == 400


async def test_km_api_027_cannot_self_register_as_admin(client) -> None:  # type: ignore[no-untyped-def]
    """Admin is never self-serve, whatever code the caller holds."""
    r = await client.post(
        "/auth/register",
        json={
            "username": f"calon-admin-{uuid.uuid4().hex[:6]}",
            "password": "kata-sandi-uji-123",
            "full_name": "Calon Admin",
            "role": "admin",
            "invitation_code": "APAPUN",
        },
    )
    assert r.status_code == 422, "role=admin must fail schema validation before code validation"


def test_km_api_028_jwt_settings_are_sane() -> None:
    assert settings.JWT_ALG == "HS256"
    assert settings.JWT_EXPIRE_MIN > 0
