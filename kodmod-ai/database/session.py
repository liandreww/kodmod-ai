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

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

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

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _make_engine() -> AsyncEngine:
    """Create the asyncpg engine. Tests use NullPool to avoid loop bleed."""
    use_null_pool = settings.ENV == "test"
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG and settings.ENV == "dev",
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        poolclass=NullPool if use_null_pool else None,
    )


async def init_db() -> None:
    """Initialize engine + session factory. Called once on FastAPI startup."""
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = _make_engine()
    _session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )
    # Smoke test connection — fail fast if DB is unreachable.
    try:
        async with _engine.connect() as conn:
            await conn.execute("SELECT 1")  # type: ignore[arg-type]
    except SQLAlchemyError as exc:
        logger.exception("Database connection failed at startup: %s", exc)
        raise
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
