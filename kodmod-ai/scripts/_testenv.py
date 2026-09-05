"""Shared test-environment lock for host-run test entrypoints.

`scripts/init_test_db.py` (schema + seed) and `scripts/serve_test_api.py` (the
API) run natively on the host against the ``kodmod-test`` Docker infra. Both must
pin the same test env into ``os.environ`` **before** anything imports
``config.settings`` — pydantic-settings lets ``os.environ`` win over the on-disk
``.env`` (which carries the real OpenAI key and ``DB_NAME=kodmod``).

Values mirror ``tests/conftest.py``. Both the chat models and the embeddings are
pointed at the OpenAI-compatible stub published by
``docker/docker-compose.test.yml``, so there is only ever one code path.
Everything uses ``setdefault`` so the shell can still override (``DB_NAME``,
``ENV=staging``, a real ``OPENAI_BASE_URL`` for ``@real_llm``, ``KODMOD_API_PORT``).

This module must not import ``config`` or ``database``.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Host ports published by docker/docker-compose.test.yml.
TEST_ENV: dict[str, str] = {
    "ENV": "test",
    "DEBUG": "false",
    "LOG_JSON": "true",
    "LANGCHAIN_TRACING_V2": "false",
    # Postgres — compose `postgres` service, host port 5433.
    "DB_HOST": "localhost",
    "DB_PORT": "5433",
    "DB_USER": "kodmod",
    "DB_PASSWORD": "kodmod",
    "DB_NAME": "kodmod_test",
    # Redis — compose `redis` service, host port 6380.
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6380",
    "REDIS_DB": "0",
    # Vector store. The stub honours the requested `dimensions`.
    "EMBEDDING_DIM": "1536",
    # A bigger pool than the prod default (10): the host server takes concurrent
    # load in Stages 4-9, and a FastAPI request can hold two connections at once
    # (the yield-dependency session + a nested one). 10 collapses under 20-way
    # concurrency (KM-PERF-003); the pool is pre-warmed at startup in session.py.
    "DB_POOL_SIZE": "40",
    "UPLOAD_DIR": str(ROOT / ".runtime" / "uploads"),
    "JWT_SECRET": "test-secret-not-for-prod-0123456789abcdef",
    # Chat models + embeddings → compose `llm-stub` service, host port 8099.
    "OPENAI_BASE_URL": "http://localhost:8099/v1",
    "OPENAI_API_KEY": "stub-key",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "LLM_ROUTER_MODEL": "stub-router",
    "LLM_TUTOR_MODEL": "stub-tutor",
    "LLM_QUIZ_MODEL": "stub-quiz",
    "LLM_SCORING_MODEL": "stub-scoring",
    "LLM_RECOMMENDATION_MODEL": "stub-recommendation",
    "LLM_REFLECTION_MODEL": "stub-reflection",
}


def apply_test_env() -> None:
    """Pin the test env (idempotent, shell-overridable). Call before importing settings."""
    for key, value in TEST_ENV.items():
        os.environ.setdefault(key, value)
    Path(ROOT / ".runtime" / "uploads").mkdir(parents=True, exist_ok=True)
