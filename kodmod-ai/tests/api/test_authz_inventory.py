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
    # Conscious public surface: the front door itself.
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("GET", "/auth/username-available"),
    #  - Prometheus scrape endpoint (network-restricted in deployment)
    ("MOUNT", "/metrics"),
}

# Endpoints that ship with no auth but are NOT a conscious allowlist entry.
# Empty is the target state; add an entry here only with a finding reference.
KNOWN_UNAUTH_GAPS: set[tuple[str, str]] = set()


def _unauth_routes():
    from api.main import app

    out = set()
    for methods, path, route in iter_routes(app):
        deps = route_dependency_names(route)
        # Role gates are built by `require_roles(...)`, which names each closure
        # `require_<roles>`; `current_user` covers the any-signed-in-account case.
        authed = any(d == "current_user" or d.startswith("require_") for d in deps)
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


def test_km_api_030b_known_gaps_are_closed() -> None:
    unauth = _unauth_routes()
    still_open = unauth & KNOWN_UNAUTH_GAPS
    assert not still_open, f"still unauthenticated: {sorted(still_open)}"
