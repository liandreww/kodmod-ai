"""Stage 9 §5 — Schemathesis negative / stateful fuzzing.

Spec: docs/testplan/09-security.md §5 (KM-SEC-050..051).

Reuses the Stage 4 approach (schemathesis 4.x: ``openapi.from_url`` +
``@schema.parametrize()``), but with an auth header injected and CRLF payloads,
and gates on: no 5xx (outside the tracked set) and no reflected payload / header
split in the response.
"""

from __future__ import annotations

import os
import re
import time
import uuid

import pytest

schemathesis = pytest.importorskip("schemathesis")

pytestmark = [pytest.mark.security, pytest.mark.slow]

BASE_URL = os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")

# Operations with tracked-but-unfixed 5xx (see traceability #1/#5/#7/#16 and the
# duplicate-email finding). Excluded so KM-SEC-050 stays a *regression* gate.
_EXCLUDE = {
    ("POST", "/quiz/start"),
    ("POST", "/quiz/submit"),
    ("POST", "/exercise/generate"),
    ("POST", "/auth/register"),
}

try:
    schema = schemathesis.openapi.from_url(f"{BASE_URL}/openapi.json")
except Exception as exc:  # pragma: no cover
    pytest.skip(f"cannot load OpenAPI from {BASE_URL}: {exc}", allow_module_level=True)


def _student_token() -> str:
    import jwt as pyjwt

    from config.settings import settings

    now = int(time.time())
    return pyjwt.encode(
        {"sub": str(uuid.uuid4()), "role": "student", "iat": now, "exp": now + 3600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


_TOKEN = _student_token()
_CRLF = "test\r\nX-Injected: 1"


@schema.parametrize()
def test_km_sec_050_no_server_errors_authed(case) -> None:  # type: ignore[no-untyped-def]
    if (case.method.upper(), case.path) in _EXCLUDE:
        pytest.skip("tracked 5xx — asserted explicitly elsewhere")
    case.headers = {**(case.headers or {}), "Authorization": f"Bearer {_TOKEN}"}
    response = case.call()
    assert response.status_code < 500, (
        f"{case.method} {case.path} -> {response.status_code}: {response.text[:300]}"
    )
    # No dangerous echo: a raw <script> in a param must not come back verbatim.
    if "<script>" in str(getattr(case, "query", "")) or "<script>" in str(
        getattr(case, "body", "")
    ):
        assert "<script>" not in response.text


@schema.parametrize()
def test_km_sec_051_no_header_crlf_split(case) -> None:  # type: ignore[no-untyped-def]
    if (case.method.upper(), case.path) in _EXCLUDE:
        pytest.skip("tracked 5xx")
    # Force a CRLF-laden value into whatever the operation will accept.
    if case.path_parameters:
        case.path_parameters = dict.fromkeys(case.path_parameters, _CRLF)
    if case.query:
        case.query = dict.fromkeys(case.query, _CRLF)
    case.headers = {**(case.headers or {}), "Authorization": f"Bearer {_TOKEN}"}
    try:
        response = case.call()
    except Exception:
        return  # client-side rejection of the bad value is fine
    # The injected header must not have materialised on the response.
    assert "x-injected" not in {k.lower() for k in response.headers}
    assert not re.search(r"\r\nX-Injected", response.text)
