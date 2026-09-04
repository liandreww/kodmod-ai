"""
KODMOD AI — Async Database Session
==================================

Owns the async SQLAlchemy engine and session factory. Used by:
- FastAPI dependencies (`api/dependencies.py`)
- Analytics persistence (analytics_agent → analytics_reports)
- Student model BKT writes (analytics/student_model.py)
- Quiz persistence (scoring_agent → quiz_attempts)

The engine is shared process-wide. Each request/agent call gets its own
session via the `async_session()` async context manager.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from config.settings import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine() -> AsyncEngine:
    """Create the asyncpg engine.

    In-process pytest uses NullPool to avoid event-loop bleed between tests
    (a pooled connection bound to a torn-down loop breaks the next test).
    A host-run server (``scripts/serve_test_api``) also sets ``ENV=test`` but
    has one long-lived loop, so it must keep a real pool — NullPool there means
    a fresh asyncpg connection per checkout, which collapses under concurrency
    (KM-PERF-003/004/010/020). Gate on "am I under pytest", not just ``ENV``.

    NullPool has no notion of pool sizing (every checkout opens a fresh
    connection), so `pool_size`/`max_overflow` must be omitted when it's
    selected — SQLAlchemy raises `TypeError` if they're passed alongside it.
    """
    use_null_pool = settings.ENV == "test" and "pytest" in sys.modules
    kwargs: dict = {
        "echo": settings.DEBUG and settings.ENV == "dev",
        "pool_pre_ping": True,
    }
    if use_null_pool:
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    return create_async_engine(settings.DATABASE_URL, **kwargs)


async def init_db() -> None:
    """Initialize engine + session factory. Called once on FastAPI startup."""
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = _make_engine()
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    # Smoke test connection — fail fast if DB is unreachable.
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("Database connection failed at startup: %s", exc)
        raise
    # Pre-warm the pool. A fresh asyncpg connection costs ~25 ms; without this the
    # first concurrent request burst pays that per connection on the event loop
    # (a p95 killer for KM-PERF-003). NullPool (pytest) has nothing to warm.
    if not isinstance(_engine.pool, NullPool):
        warm = settings.DB_POOL_SIZE
        try:
            conns = await asyncio.gather(*(_engine.connect() for _ in range(warm)))
            await asyncio.gather(*(c.close() for c in conns))
        except SQLAlchemyError:
            logger.warning("Pool pre-warm skipped (could not open %d connections)", warm)
    logger.info("Database initialized (host=%s db=%s)", settings.DB_HOST, settings.DB_NAME)


async def close_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed")


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    return _engine


@asynccontextmanager
async def async_session() -> AsyncIterator[AsyncSession]:
    """
    Async context manager yielding a transactional session.
    Auto-commits on clean exit, rollbacks on exception.

    Usage:
        async with async_session() as session:
            await session.execute(...)
    """
    if _session_factory is None:
        raise RuntimeError("DB not initialized — call init_db() first")

    session: AsyncSession = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency variant (non-context-manager)."""
    if _session_factory is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    session: AsyncSession = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
