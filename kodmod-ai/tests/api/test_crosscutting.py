"""Stage 4 §11 — cross-cutting: CORS, 404/405, malformed body, /metrics.

Spec: docs/testplan/04-api.md §11 (KM-API-110..114).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


@pytest.mark.known_bug(
    "CORS — api/main.py sets allow_credentials=True with allow_origins possibly ['*']; the "
    "Fetch spec forbids that combination (must be explicit origins or credentials=False)"
)
async def test_km_api_110_cors_preflight(client) -> None:  # type: ignore[no-untyped-def]
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


async def test_km_api_111_404_json(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/definitely/not/a/route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


async def test_km_api_112_405_method(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.request("DELETE", "/student/me", headers=auth_headers(tok))
    assert r.status_code == 405


async def test_km_api_113_malformed_json(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/content/retrieve",
        headers={"Content-Type": "application/json"},
        content='{"query": ',
    )
    assert r.status_code == 422


async def test_km_api_114_metrics_prometheus(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/metrics/")  # /metrics 307-redirects to /metrics/
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "version=0.0.4" in r.headers["content-type"]
    assert "# HELP" in r.text
