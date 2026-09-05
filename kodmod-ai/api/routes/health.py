"""
KODMOD AI — Health & Readiness Routes
=====================================

- GET /health/live    -> liveness (process is up)
- GET /health/ready   -> readiness (DB + Redis reachable)
- GET /health/version -> build / version metadata
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/live")
async def live() -> dict[str, Any]:
    """Liveness probe — returns 200 as long as the process is running."""
    return {"status": "alive", "ts": datetime.now(UTC).isoformat()}


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness probe — checks that Postgres and Redis are reachable."""
    checks: dict[str, Any] = {}
    overall = True

    # DB
    try:
        from database.session import async_session

        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"fail: {exc!s}"
        overall = False

    # Redis
    try:
        from memory.short_term import get_redis

        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail: {exc!s}"
        # Redis is non-critical (graph still works without short-term cache)
        # so we don't flip overall.

    response = {
        "status": "ready" if overall else "degraded",
        "checks": checks,
        "ts": datetime.now(UTC).isoformat(),
    }
    return response


@router.get("/version")
async def version() -> dict[str, Any]:
    """Build and runtime metadata: app version, env, and the configured models."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.ENV,
        "tutor_model": settings.LLM_TUTOR_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
    }
