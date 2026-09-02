"""Stage 4 §1 — health endpoints (mounted with NO /health prefix).

Spec: docs/testplan/04-api.md §1 (KM-API-001..006).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def test_km_api_001_live(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "alive"
    assert "ts" in body


async def test_km_api_002_ready_healthy(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ready", "degraded"}
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


async def test_km_api_005_version(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/version")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "name",
        "version",
        "env",
        "llm_provider",
        "vector_backend",
        "stt_backend",
        "tts_backend",
    ):
        assert key in body
    assert body["env"] == "test"


async def test_km_api_006_no_health_prefix(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/health")).status_code == 404
    assert (await client.get("/health/live")).status_code == 404
