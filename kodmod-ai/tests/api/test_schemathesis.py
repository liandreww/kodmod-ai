"""Stage 4 §10 — contract fuzzing with Schemathesis against the live container.

Spec: docs/testplan/04-api.md §10 (KM-API-100..102).

Every 5xx Schemathesis finds is a real defect. The endpoints whose 5xx are
already tracked (#1 quiz/voice, #7 exercise/generate, #16 non-UUID sub) are
excluded here so this stays a *regression* gate; they are asserted explicitly
in test_quiz / test_voice / test_exercise / test_auth.
"""

from __future__ import annotations

import os

import pytest

schemathesis = pytest.importorskip("schemathesis")

pytestmark = [pytest.mark.api, pytest.mark.slow]

BASE_URL = os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")

# Operations with tracked-but-unfixed 5xx (see module docstring).
_EXCLUDE = {
    ("POST", "/quiz/start"),
    ("POST", "/quiz/submit"),
    ("POST", "/voice/text"),
    ("POST", "/voice/chat"),
    ("POST", "/exercise/generate"),
    # new finding: duplicate/empty email -> unhandled IntegrityError -> 500.
    # Asserted explicitly in test_student.py::test_km_api_040b_duplicate_email.
    ("POST", "/student"),
}

try:
    schema = schemathesis.openapi.from_url(f"{BASE_URL}/openapi.json")
except Exception as exc:  # pragma: no cover
    pytest.skip(f"cannot load OpenAPI from {BASE_URL}: {exc}", allow_module_level=True)


@schema.parametrize()
def test_km_api_100_no_server_errors(case) -> None:  # type: ignore[no-untyped-def]
    if (case.method.upper(), case.path) in _EXCLUDE:
        pytest.skip("tracked 5xx — asserted explicitly elsewhere")
    # KM-API-100 gates only on "no server error" (5xx). Status-code / schema
    # conformance is a separate concern tracked in the contract stage.
    response = case.call()
    assert response.status_code < 500, (
        f"{case.method} {case.path} returned {response.status_code}: {response.text[:300]}"
    )
