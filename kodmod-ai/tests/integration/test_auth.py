"""Stage 3 — Integration: registration, login, and invitation codes.

Real Postgres, real bcrypt, no HTTP. These exercise the rules that decide who
gets an account, so they are written as the attacks they are meant to stop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.routes.auth import login, register
from api.security import hash_password, verify_password
from database.models import InvitationCode, User
from models.user import LoginRequest, RegisterRequest
from tests.conftest import TEST_PASSWORD

pytestmark = [pytest.mark.integration, pytest.mark.db]


async def _make_code(db_session, **overrides) -> InvitationCode:
    data = {
        "code": overrides.pop("code", f"CODE{uuid.uuid4().hex[:6].upper()}"),
        "max_uses": overrides.pop("max_uses", 1),
        "used_count": overrides.pop("used_count", 0),
        "is_active": overrides.pop("is_active", True),
    }
    data.update(overrides)
    invite = InvitationCode(**data)
    db_session.add(invite)
    await db_session.flush()
    return invite


def _register_body(code: str, **overrides) -> RegisterRequest:
    payload = {
        "username": overrides.pop("username", f"user{uuid.uuid4().hex[:8]}"),
        "password": TEST_PASSWORD,
        "full_name": "Pengguna Uji",
        "role": overrides.pop("role", "student"),
        "invitation_code": code,
    }
    payload.update(overrides)
    return RegisterRequest(**payload)


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def test_password_hash_is_salted_and_verifiable() -> None:
    a, b = hash_password(TEST_PASSWORD), hash_password(TEST_PASSWORD)
    assert a != b, "identical passwords must not produce identical hashes"
    assert verify_password(TEST_PASSWORD, a)
    assert not verify_password("wrong-password", a)


def test_password_verify_survives_a_garbage_hash() -> None:
    """A corrupt row must fail the login, not crash the endpoint."""
    assert verify_password(TEST_PASSWORD, "not-a-bcrypt-hash") is False


@pytest.mark.parametrize("bad", ["short", "x" * 73])
def test_password_length_bounds_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        hash_password(bad)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
async def test_register_creates_account_and_spends_the_code(db_session) -> None:
    invite = await _make_code(db_session)
    body = _register_body(invite.code, username="budi")

    result = await register(body, session=db_session)

    assert result.user.username == "budi"
    assert result.user.role == "student"
    assert result.access_token
    assert invite.used_count == 1

    row = (await db_session.execute(select(User).where(User.username == "budi"))).scalar_one()
    assert row.password_hash != TEST_PASSWORD
    assert verify_password(TEST_PASSWORD, row.password_hash)


async def test_register_rejects_unknown_code(db_session) -> None:
    with pytest.raises(HTTPException) as exc:
        await register(_register_body("NOSUCHCODE"), session=db_session)
    assert exc.value.status_code == 400


async def test_register_rejects_exhausted_code(db_session) -> None:
    invite = await _make_code(db_session, max_uses=1, used_count=1)
    with pytest.raises(HTTPException) as exc:
        await register(_register_body(invite.code), session=db_session)
    assert exc.value.status_code == 400


async def test_register_rejects_expired_code(db_session) -> None:
    invite = await _make_code(db_session, expires_at=datetime.now(UTC) - timedelta(days=1))
    with pytest.raises(HTTPException) as exc:
        await register(_register_body(invite.code), session=db_session)
    assert exc.value.status_code == 400


async def test_register_rejects_revoked_code(db_session) -> None:
    invite = await _make_code(db_session, is_active=False)
    with pytest.raises(HTTPException) as exc:
        await register(_register_body(invite.code), session=db_session)
    assert exc.value.status_code == 400


async def test_multi_use_code_survives_several_registrations(db_session) -> None:
    invite = await _make_code(db_session, max_uses=3)
    for _ in range(3):
        await register(_register_body(invite.code), session=db_session)
    assert invite.used_count == 3
    with pytest.raises(HTTPException):
        await register(_register_body(invite.code), session=db_session)


async def test_register_rejects_duplicate_username(db_session) -> None:
    first = await _make_code(db_session)
    await register(_register_body(first.code, username="kembar"), session=db_session)

    second = await _make_code(db_session)
    with pytest.raises(HTTPException) as exc:
        await register(_register_body(second.code, username="kembar"), session=db_session)
    assert exc.value.status_code == 409


async def test_student_gets_the_accessibility_default(db_session) -> None:
    invite = await _make_code(db_session)
    result = await register(_register_body(invite.code, role="student"), session=db_session)
    assert result.user.accessibility_profile == "blind"


async def test_teacher_does_not_get_the_blind_default(db_session) -> None:
    invite = await _make_code(db_session)
    result = await register(_register_body(invite.code, role="teacher"), session=db_session)
    assert result.user.accessibility_profile == "standard"


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
async def test_login_succeeds_and_stamps_last_login(db_session, user_factory) -> None:
    user, _ = await user_factory("student", username="masuk")
    assert user.last_login_at is None

    result = await login(LoginRequest(username="masuk", password=TEST_PASSWORD), session=db_session)
    assert result.user.id == user.id
    assert result.token_type == "bearer"
    assert user.last_login_at is not None


async def test_login_rejects_wrong_password(db_session, user_factory) -> None:
    await user_factory("student", username="salah")
    with pytest.raises(HTTPException) as exc:
        await login(LoginRequest(username="salah", password="not-the-password"), session=db_session)
    assert exc.value.status_code == 401


async def test_login_does_not_reveal_whether_a_username_exists(db_session, user_factory) -> None:
    """Both failures must be indistinguishable, or this becomes a user enumerator."""
    await user_factory("student", username="ada")

    with pytest.raises(HTTPException) as wrong_password:
        await login(LoginRequest(username="ada", password="salah-sekali"), session=db_session)
    with pytest.raises(HTTPException) as no_such_user:
        await login(LoginRequest(username="tidakada", password="salah-sekali"), session=db_session)

    assert wrong_password.value.status_code == no_such_user.value.status_code == 401
    assert wrong_password.value.detail == no_such_user.value.detail


async def test_disabled_account_cannot_log_in(db_session, user_factory) -> None:
    await user_factory("student", username="nonaktif", is_active=False)
    with pytest.raises(HTTPException) as exc:
        await login(LoginRequest(username="nonaktif", password=TEST_PASSWORD), session=db_session)
    assert exc.value.status_code == 403
