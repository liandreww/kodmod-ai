"""
KODMOD AI — Health & Readiness Routes
=====================================

- GET /health/live    -> liveness (process is up)
- GET /health/ready   -> readiness (DB + Redis reachable)
- GET /health/version -> build / version metadata
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import text

from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/live")
async def live() -> dict[str, Any]:
    return {"status": "alive", "ts": datetime.utcnow().isoformat()}


@router.get("/ready")
async def ready() -> dict[str, Any]:
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
        "ts": datetime.utcnow().isoformat(),
    }
    return response


@router.get("/version")
async def version() -> dict[str, Any]:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.ENV,
        "llm_provider": settings.KODMOD_LLM_PROVIDER,
        "vector_backend": settings.VECTOR_BACKEND,
        "stt_backend": settings.STT_BACKEND,
        "tts_backend": settings.TTS_BACKEND,
    }
