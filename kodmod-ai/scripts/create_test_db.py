"""
KODMOD AI — Create schema for text-mode manual testing
=====================================================

`database/schema.sql` (auto-loaded by docker-compose.yml) is out of sync with
`database/models.py` and `rag/stores/pgvector_store.py`. For local testing we
instead:

  1. create every ORM table from `database.models.Base`
  2. hand-create `curriculum_chunks` with the columns the pgvector store
     actually reads/writes (`content`, `embedding vector(1024)`, `source`,
     `language`, `concept_id`, `chunk_index`, `section_title`,
     `accessibility_metadata`, `created_at`).

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

_DDL: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    # `create_all` never ALTERs an existing table — heal a pre-existing test DB
    # whose `classrooms.teacher_id` was created NOT NULL before the ORM made it
    # nullable (idempotent: no-op if already nullable).
    "ALTER TABLE classrooms ALTER COLUMN teacher_id DROP NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS curriculum_chunks (
        id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        content                TEXT NOT NULL,
        embedding              vector(1024) NOT NULL,
        source                 TEXT NOT NULL DEFAULT '',
        language               VARCHAR(8) NOT NULL DEFAULT 'id',
        concept_id             UUID,
        chunk_index            INT NOT NULL DEFAULT 0,
        section_title          TEXT,
        accessibility_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cc_embedding_hnsw "
    "ON curriculum_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_cc_concept ON curriculum_chunks (concept_id)",
    "CREATE INDEX IF NOT EXISTS idx_cc_source ON curriculum_chunks (source)",
]


async def _amain() -> None:
    await init_db()
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in _DDL:
                await conn.execute(text(stmt))
        logger.info(
            "Test schema ready: %d ORM tables + curriculum_chunks", len(Base.metadata.tables)
        )
    finally:
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_amain())
