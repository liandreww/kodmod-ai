"""
KODMOD AI — Create the test schema
==================================

`database/models.py` is the whole schema, `curriculum_chunks` included, so this
is just "enable the extensions, then create_all". Production goes through
Alembic (`make migrate`); tests skip the migration chain because a fresh
database from the models is faster and equally correct.

Run once, after `docker compose -f docker/docker-compose.test.yml up -d`:

    python -m scripts.create_test_db
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from database.models import Base
from database.session import close_db, get_engine, init_db

logger = logging.getLogger(__name__)

_EXTENSIONS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
)


async def _amain() -> None:
    await init_db()
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            for stmt in _EXTENSIONS:
                await conn.execute(text(stmt))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Test schema ready: %d tables", len(Base.metadata.tables))
    finally:
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_amain())
