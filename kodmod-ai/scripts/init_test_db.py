"""
KODMOD AI — Bootstrap the test database on the host
==================================================

Replaces the old one-shot `db-init` container. Locks the test env (so it talks
to the ``kodmod-test`` Postgres = DB ``kodmod_test`` on host port 5433, **not**
the ``kodmod`` DB from the on-disk ``.env``), then:

  1. creates the schema  — ``scripts.create_test_db`` (ORM ``create_all`` +
     ``curriculum_chunks`` DDL)
  2. seeds the curriculum — ``scripts.seed_curriculum`` (idempotent)

Run from ``kodmod-ai/`` after the infra is up::

    docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub
    python -m scripts.init_test_db

Idempotent — safe to re-run. ``scripts/run_tests.{ps1,sh}`` call this for Stage 3+.
"""

from __future__ import annotations

import asyncio
import logging

from scripts._testenv import apply_test_env


def main() -> None:
    apply_test_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Imported only after the env is pinned — these pull in config.settings.
    from scripts.create_test_db import _amain as create_schema
    from scripts.seed_curriculum import main as seed_curriculum

    async def _run() -> None:
        await create_schema()
        await seed_curriculum()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
