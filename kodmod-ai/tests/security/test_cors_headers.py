"""Stage 9 §6 — CORS / security headers / error verbosity.

Spec: docs/testplan/09-security.md §6 (KM-SEC-060..063).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.security, pytest.mark.asyncio(loop_scope="session")]


# --------------------------------------------------------------------------- #
# KM-SEC-060 — CORS: never "*" + credentials
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "CORS — api/main.py registers CORSMiddleware with allow_credentials=True while "
    "CORS_ALLOW_ORIGINS defaults to ['*']; the Fetch spec forbids that pairing. Target: "
    "explicit origins, or credentials disabled"
)
async def test_km_sec_060_cors_star_with_credentials(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.options(
        "/student/me",
        headers={
            "Origin": "http://evil.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = r.headers.get("access-control-allow-origin")
    acac = r.headers.get("access-control-allow-credentials")
    assert not (acao == "*" and acac == "true")
    # And it must not reflect an arbitrary attacker origin together with credentials.
    assert not (acao == "http://evil.test" and acac == "true")


# --------------------------------------------------------------------------- #
# KM-SEC-061 — baseline security headers (advisory)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "security headers — /live returns none of X-Content-Type-Options, X-Frame-Options, "
    "Referrer-Policy (HSTS is terminated at Caddy in prod). Advisory: add them if it "
    "becomes policy"
)
async def test_km_sec_061_security_headers_present(client) -> None:  # type: ignore[no-untyped-def]
    h = {k.lower() for k in (await client.get("/live")).headers}
    missing = {"x-content-type-options", "x-frame-options", "referrer-policy"} - h
    assert not missing, f"missing security headers: {sorted(missing)}"


# --------------------------------------------------------------------------- #
# KM-SEC-062 — /metrics not publicly exposed
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#14 — /metrics is mounted with no auth and no network restriction; target: token- or "
    "network-gated"
)
async def test_km_sec_062_metrics_protected(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/metrics/")
    assert r.status_code in {401, 403}


# --------------------------------------------------------------------------- #
# KM-SEC-063 — 500s are generic when DEBUG is off
# --------------------------------------------------------------------------- #
async def test_km_sec_063_error_verbosity(client) -> None:  # type: ignore[no-untyped-def]
    from config.settings import settings

    if settings.DEBUG:
        pytest.skip("DEBUG=true — verbose errors are expected; this check is for prod config")

    # A non-UUID sub currently trips a 500 in some builds (#16). Whatever the
    # status, the body must not carry a traceback / SQL / file paths.
    import time
    import uuid

    import jwt as pyjwt

    now = int(time.time())
    tok = pyjwt.encode(
        {"sub": "definitely-not-a-uuid", "role": "student", "iat": now, "exp": now + 3600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )
    r = await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
    body = r.text
    for needle in ("Traceback (most recent call last)", 'File "/', "psycopg", "asyncpg", "SELECT "):
        assert needle not in body, f"error body leaks internals: {needle!r}"
    # A well-formed but unknown random UUID -> 404, still generic.
    tok2 = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "role": "student", "iat": now, "exp": now + 3600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )
    r2 = await client.get("/student/me", headers={"Authorization": f"Bearer {tok2}"})
    assert r2.status_code == 404
    assert "Traceback" not in r2.text
