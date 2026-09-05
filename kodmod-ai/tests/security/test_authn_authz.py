"""Stage 9 §1 — AuthN / AuthZ against the running api.

Spec: docs/testplan/09-security.md §1 (KM-SEC-001..015).

Per the campaign policy (README §2/§6.1) a control that is not yet enforced is a
plain assertion of the TARGET behaviour + ``@pytest.mark.known_bug`` — RED until
the fix lands, then GREEN. The staged runner selects ``-m "security and not
known_bug"`` so Stage 9 still gates regressions.
"""

from __future__ import annotations

import uuid

import pytest

from tests.security import _jwt_attacks as atk

pytestmark = [pytest.mark.security, pytest.mark.asyncio(loop_scope="session")]

REF = "/auth/me"  # reference protected endpoint


# --------------------------------------------------------------------------- #
# KM-SEC-001..004 — signature / algorithm / expiry
# --------------------------------------------------------------------------- #
async def test_km_sec_001_alg_none_rejected(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(REF, headers={"Authorization": f"Bearer {atk.alg_none()}"})
    assert r.status_code == 401


async def test_km_sec_002_wrong_signature_rejected(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(REF, headers={"Authorization": f"Bearer {atk.wrong_secret()}"})
    assert r.status_code == 401


async def test_km_sec_003_tampered_payload_rejected(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    st, _tok = await student_factory()
    forged = atk.tampered_role(st.id, "teacher")
    r = await client.get("/analytics/cohort", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401  # signature no longer verifies


async def test_km_sec_004_expired_rejected(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(REF, headers={"Authorization": f"Bearer {atk.expired()}"})
    assert r.status_code == 401
    assert "expired" in r.text.lower()


# --------------------------------------------------------------------------- #
# KM-SEC-005 — no aud / iss / nbf validation  (target: validate or document)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#16 — _decode_jwt passes no audience/issuer options; a token with a foreign aud/iss but a "
    "valid signature + exp is accepted. Target: validate iss/aud or record a conscious decision"
)
async def test_km_sec_005_foreign_aud_iss_rejected(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    st, _tok = await student_factory()
    forged = atk.foreign_aud_iss(st.id, "student")
    r = await client.get(REF, headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# KM-SEC-006 — non-UUID / SQL-ish sub
# --------------------------------------------------------------------------- #
async def test_km_sec_006_sub_not_uuid(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(REF, headers={"Authorization": f"Bearer {atk.sub_not_uuid()}"})
    assert r.status_code in {401, 422}, r.text[:200]
    assert "Traceback" not in r.text


async def test_km_sec_006b_sub_sql_payload(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get(REF, headers={"Authorization": f"Bearer {atk.sub_sql()}"})
    assert r.status_code in {401, 422}
    assert "Traceback" not in r.text and "syntax error" not in r.text.lower()


# --------------------------------------------------------------------------- #
# KM-SEC-007 — privilege escalation student -> teacher
# --------------------------------------------------------------------------- #
async def test_km_sec_007_student_cannot_reach_teacher_route(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.get("/analytics/cohort", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "teacher" in r.text.lower()


# --------------------------------------------------------------------------- #
# KM-SEC-008..009 — IDOR on analytics
# --------------------------------------------------------------------------- #
async def test_km_sec_008_idor_student_analytics(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _a, tok = await student_factory()
    victim, _v = await student_factory()
    r = await client.get(
        f"/analytics/student/{victim.id}", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 403


async def test_km_sec_009_idor_student_spoken(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _a, tok = await student_factory()
    victim, _v = await student_factory()
    r = await client.get(
        f"/analytics/student/{victim.id}/spoken", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# KM-SEC-010 — IDOR on /student/{id}/profile
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#14 — GET /student/{id}/profile historically shipped with no owner check; target: a "
    "student may read only their own profile (401/403 for others)"
)
async def test_km_sec_010_idor_student_profile(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    victim, _v = await student_factory(full_name="Korban")
    _atk, atk_tok = await student_factory(full_name="Penyerang")
    r = await client.get(
        f"/student/{victim.id}/profile", headers={"Authorization": f"Bearer {atk_tok}"}
    )
    assert r.status_code in {401, 403}


# --------------------------------------------------------------------------- #
# KM-SEC-011 — IDOR on /exercise/generate
# --------------------------------------------------------------------------- #
async def test_km_sec_011_exercise_generate_ignores_a_forged_owner(  # type: ignore[no-untyped-def]
    client, student_factory, concept_ids
) -> None:
    """IDOR is designed out: the schema has no student_id, so the token decides.

    A caller can still *send* one. It must be ignored, not honoured.
    """
    _atk, tok = await student_factory()
    victim, _v = await student_factory()
    r = await client.post(
        "/exercise/generate",
        headers={"Authorization": f"Bearer {tok}"},
        json={"student_id": str(victim.id), "concept_id": concept_ids["pecahan"], "n_questions": 1},
    )
    assert r.status_code == 200
    assert str(victim.id) not in r.text


# --------------------------------------------------------------------------- #
# KM-SEC-012 — IDOR on /quiz/*
# --------------------------------------------------------------------------- #
async def test_km_sec_012_quiz_start_ignores_a_forged_owner(  # type: ignore[no-untyped-def]
    client, student_factory, concept_ids
) -> None:
    """The quiz session belongs to the token holder, never to a body field."""
    from sqlalchemy import text

    from database.session import async_session

    _atk, tok = await student_factory()
    victim, _v = await student_factory()
    r = await client.post(
        "/quiz/start",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "student_id": str(victim.id),
            "concept_id": concept_ids["pecahan"],
            "n_questions": 1,
            "difficulty": "easy",
        },
    )
    assert r.status_code == 200
    session_id = r.json()["quiz_session_id"]

    async with async_session() as s:
        owner = (
            await s.execute(
                text("SELECT student_id FROM quiz_sessions WHERE id = CAST(:id AS uuid)"),
                {"id": session_id},
            )
        ).scalar_one()
    assert str(owner) != str(victim.id)


# --------------------------------------------------------------------------- #
# KM-SEC-013 — unauthenticated-endpoint inventory (security gate)
# --------------------------------------------------------------------------- #
_ALLOWLIST = {
    ("GET", "/live"),
    ("GET", "/ready"),
    ("GET", "/version"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/redoc"),
    ("GET", "/docs/oauth2-redirect"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("GET", "/auth/username-available"),
}
# Deliberately unauthenticated but not part of the product surface: Prometheus
# is expected to be network-restricted at deploy time.
_KNOWN_GAPS = {
    ("MOUNT", "/metrics"),
}


def _unauth_routes() -> set[tuple[str, str]]:
    from api.main import app
    from tests.contract.conftest import iter_routes, route_dependency_names

    out: set[tuple[str, str]] = set()
    for methods, path, route in iter_routes(app):
        deps = route_dependency_names(route)
        authed = "current_student" in deps or "current_teacher" in deps
        if authed:
            continue
        for m in methods:
            if m in {"HEAD", "OPTIONS", "WEBSOCKET"}:
                continue
            out.add((m, path))
    return out


def test_km_sec_013a_no_unexpected_unauth_endpoints() -> None:
    extra = _unauth_routes() - _ALLOWLIST - _KNOWN_GAPS
    assert not extra, f"new unauthenticated endpoints: {sorted(extra)}"


@pytest.mark.known_bug(
    "#14 — /metrics is reachable with no auth; acceptable only because deployment is "
    "expected to restrict it at the network layer"
)
def test_km_sec_013b_known_gaps_closed() -> None:
    still_open = _unauth_routes() & _KNOWN_GAPS
    assert not still_open, f"still unauthenticated: {sorted(still_open)}"


# --------------------------------------------------------------------------- #
# KM-SEC-014 — JWT secret is not the shipped placeholder
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#15 — config/settings.py defaults JWT_SECRET to 'change-me-in-production'; the running api "
    "must be started with a real secret from env/secret store, never the default"
)
def test_km_sec_014_jwt_secret_not_default() -> None:
    from config.settings import settings

    assert settings.JWT_SECRET != "change-me-in-production"


# --------------------------------------------------------------------------- #
# KM-SEC-015 — invalid tokens all 401, no timing oracle for sub validity
# --------------------------------------------------------------------------- #
async def test_km_sec_015_bruteforce_all_401(client) -> None:  # type: ignore[no-untyped-def]
    import time

    real_shape_times: list[float] = []
    junk_times: list[float] = []
    for i in range(25):
        t = atk.wrong_secret(uuid.uuid4()) if i % 2 else "garbage." * 3
        start = time.perf_counter()
        r = await client.get(REF, headers={"Authorization": f"Bearer {t}"})
        dt = time.perf_counter() - start
        assert r.status_code == 401
        (real_shape_times if i % 2 else junk_times).append(dt)

    # No gross timing oracle: the two populations' means stay within an order of
    # magnitude of each other (loose — this is a smoke, not a side-channel lab).
    m_real = sum(real_shape_times) / len(real_shape_times)
    m_junk = sum(junk_times) / len(junk_times)
    ratio = max(m_real, m_junk) / max(min(m_real, m_junk), 1e-6)
    assert ratio < 20.0, f"suspicious timing gap: {m_real:.4f}s vs {m_junk:.4f}s"
