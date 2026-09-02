"""Stage 4 §3 — unauthenticated-endpoint allowlist.

Spec: docs/testplan/04-api.md §3 (KM-API-030). Static introspection of api.main:app.
"""

from __future__ import annotations

import pytest

from tests.contract.conftest import iter_routes, route_dependency_names

pytestmark = [pytest.mark.api]

ALLOWLIST = {
    ("GET", "/live"),
    ("GET", "/ready"),
    ("GET", "/version"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/redoc"),
    ("GET", "/docs/oauth2-redirect"),
}

# Endpoints that currently ship with no auth but are NOT a conscious allowlist entry.
KNOWN_UNAUTH_GAPS = {
    ("POST", "/student"),
    ("GET", "/student/{student_id}/profile"),
    ("GET", "/content/concepts"),
    ("GET", "/content/concepts/{concept_id}"),
    ("GET", "/content/concepts/{concept_id}/lessons"),
    ("POST", "/content/retrieve"),
    ("GET", "/exercise/by-concept/{concept_id}"),
    ("MOUNT", "/metrics"),
}


def _unauth_routes():
    from api.main import app

    out = set()
    for methods, path, route in iter_routes(app):
        deps = route_dependency_names(route)
        authed = "current_student" in deps or "current_teacher" in deps
        for m in methods:
            if m in {"HEAD", "OPTIONS", "WEBSOCKET"}:
                # WS auth is enforced in-handler via authenticate_ws(?token=),
                # not as a Depends dependency — covered by Stage 5 (KM-WS-001..006).
                continue
            if not authed:
                out.add((m, path))
    return out


def test_km_api_030a_no_new_unauth_endpoints() -> None:
    unauth = _unauth_routes()
    unexpected = unauth - ALLOWLIST - KNOWN_UNAUTH_GAPS
    assert not unexpected, f"new unauthenticated endpoints (not allowlisted): {sorted(unexpected)}"


@pytest.mark.known_bug(
    "#14 — POST /student, GET /student/{id}/profile, all /content/*, "
    "GET /exercise/by-concept/{id} and /metrics are served with no auth and are not a "
    "conscious allowlist entry"
)
def test_km_api_030b_known_gaps_are_closed() -> None:
    unauth = _unauth_routes()
    still_open = unauth & KNOWN_UNAUTH_GAPS
    assert not still_open, f"still unauthenticated: {sorted(still_open)}"
