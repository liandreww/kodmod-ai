"""KM-UNIT-140..143 — pure JWT decode helper (api/dependencies._decode_jwt).

Oracle: PyJWT semantics + the HS256 algorithm pinned in settings.
Spec: docs/testplan/01-unit.md §10.
"""

from __future__ import annotations

import base64
import json
import time
import uuid

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from api.dependencies import _decode_jwt
from config.settings import settings

pytestmark = pytest.mark.unit


def _encode(payload: dict, *, secret: str | None = None) -> str:
    return pyjwt.encode(payload, secret or settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def test_round_trip() -> None:  # KM-UNIT-140
    sub = str(uuid.uuid4())
    token = _encode({"sub": sub, "role": "student", "exp": int(time.time()) + 3600})
    payload = _decode_jwt(token)
    assert payload["sub"] == sub
    assert payload["role"] == "student"


def test_expired_token_raises_401() -> None:  # KM-UNIT-141
    token = _encode({"sub": "x", "role": "student", "exp": int(time.time()) - 10})
    with pytest.raises(HTTPException) as exc:
        _decode_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Token expired"


def test_wrong_secret_raises_401() -> None:  # KM-UNIT-142
    token = _encode({"sub": "x", "role": "student"}, secret="a-totally-different-secret")
    with pytest.raises(HTTPException) as exc:
        _decode_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail.startswith("Invalid token")


def test_alg_none_is_rejected() -> None:  # KM-UNIT-143
    def _b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': 'x', 'role': 'student'})}."
    with pytest.raises(HTTPException) as exc:
        _decode_jwt(unsigned)
    assert exc.value.status_code == 401
