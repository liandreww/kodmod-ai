"""Malicious-token assembly for Stage 9 AuthN tests (docs/testplan/09-security.md §1)."""

from __future__ import annotations

import base64
import json
import time
import uuid

import jwt as pyjwt

from config.settings import settings


def _claims(sub: object = None, role: str = "student", **extra: object) -> dict:
    now = int(time.time())
    return {
        "sub": str(sub) if sub is not None else str(uuid.uuid4()),
        "role": role,
        "iat": now,
        "exp": now + 3600,
        **extra,
    }


def valid(sub: object = None, role: str = "student", **extra: object) -> str:
    return pyjwt.encode(
        _claims(sub, role, **extra), settings.JWT_SECRET, algorithm=settings.JWT_ALG
    )


def alg_none(sub: object = None, role: str = "student") -> str:
    """Unsigned token with ``{"alg":"none"}`` — PyJWT must reject it on decode."""
    return pyjwt.encode(_claims(sub, role), key="", algorithm="none")


def wrong_secret(sub: object = None, role: str = "student") -> str:
    return pyjwt.encode(_claims(sub, role), "x" * 32, algorithm="HS256")


def expired(sub: object = None, role: str = "student") -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": str(sub or uuid.uuid4()), "role": role, "iat": now - 7200, "exp": now - 3600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


def tampered_role(sub: object, new_role: str = "teacher") -> str:
    """Take a validly-signed student token, swap ``role`` in the payload, keep the old sig."""
    tok = valid(sub, "student")
    head, payload, sig = tok.split(".")
    raw = json.loads(base64.urlsafe_b64decode(payload + "=="))
    raw["role"] = new_role
    new_payload = base64.urlsafe_b64encode(json.dumps(raw).encode()).rstrip(b"=").decode()
    return f"{head}.{new_payload}.{sig}"


def foreign_aud_iss(sub: object = None, role: str = "student") -> str:
    """Validly signed, ``exp`` fresh, but ``aud``/``iss`` belong to someone else."""
    return valid(sub, role, aud="https://evil.test", iss="https://evil.test")


def sub_sql(role: str = "student") -> str:
    return valid("'; DROP TABLE students;--", role)


def sub_not_uuid(role: str = "student") -> str:
    return valid("not-a-uuid-at-all", role)
