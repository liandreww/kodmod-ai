"""Shared pytest fixtures for the KODMOD test suite.

Stage map (see docs/testplan/):
  0 static      1 unit        2 contract    3 integration   4 api
  5 ws          6 e2e         7 system      8 perf          9 security

kodmod-ai runs entirely in Docker (docker/docker-compose.test.yml: postgres,
redis, llm-stub, api). Test SCRIPTS run natively on the host (PowerShell or
bash), never inside a container:
  * Stage 1 (unit) needs no service at all.
  * Stage 3 (integration) calls Python functions directly in this process and
    talks to Postgres/Redis over their published ports.
  * Stage 4-9 (api/ws/e2e/system/perf/security) talk to the real `api`
    container over HTTP/WS — see the `client`/`ws_url` fixtures below. Bring
    the stack up first: `docker compose -p kodmod-test -f
    docker/docker-compose.test.yml up -d --build api`.

Environment is forced to ``test`` BEFORE any project import so the cached
``config.settings`` singleton picks up test values. For Stage 1/3, LLM and
embedding calls made *in this process* are stubbed by autouse fixtures unless
a test is marked ``real_llm``. For Stage 4+, the `api` container stubs its own
LLM/embedding calls via env (KODMOD_LLM_PROVIDER=vllm -> the llm-stub service).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest

# --------------------------------------------------------------------------- #
# Environment — must run at import time, before anything imports settings.
# --------------------------------------------------------------------------- #
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("KODMOD_LLM_PROVIDER", "anthropic")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DB_NAME", "kodmod_test")
os.environ.setdefault("DB_HOST", os.environ.get("DB_HOST", "localhost"))
os.environ.setdefault("DB_PORT", os.environ.get("DB_PORT", "5433"))
os.environ.setdefault("REDIS_HOST", os.environ.get("REDIS_HOST", "localhost"))
os.environ.setdefault("REDIS_PORT", os.environ.get("REDIS_PORT", "6380"))
os.environ.setdefault("EMBEDDING_DIM", "1024")
os.environ.setdefault("VECTOR_BACKEND", "pgvector")
os.environ.setdefault("STT_ENABLED", "false")
os.environ.setdefault("TTS_ENABLED", "false")
os.environ.setdefault("AUDIO_DIR", os.path.join(os.getcwd(), ".runtime", "audio"))
os.environ.setdefault("UPLOAD_DIR", os.path.join(os.getcwd(), ".runtime", "uploads"))
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod-0123456789abcdef")

RUN_REAL_LLM = os.getenv("KODMOD_RUN_REAL_LLM") == "1"

# Fixed UUIDs — see docs/testplan/test-data.md
STUDENT_BLIND = uuid.UUID("11111111-1111-1111-1111-111111111111")
STUDENT_LOWVISION = uuid.UUID("11111111-1111-1111-1111-111111111112")
STUDENT_STRONG = uuid.UUID("11111111-1111-1111-1111-111111111113")
TEACHER_A = uuid.UUID("22222222-2222-2222-2222-222222222221")
CLASSROOM_A = uuid.UUID("33333333-3333-3333-3333-333333333331")


# --------------------------------------------------------------------------- #
# Markers are registered in pyproject.toml [tool.pytest.ini_options].markers
# (single source of truth — keep the two lists in sync if either changes):
#   static, unit, contract, integration, api, ws, e2e, system, perf, security,
#   real_llm, slow, db, redis
# --------------------------------------------------------------------------- #
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_real = pytest.mark.skip(reason="real LLM disabled (set KODMOD_RUN_REAL_LLM=1)")
    for item in items:
        if "real_llm" in item.keywords and not RUN_REAL_LLM:
            item.add_marker(skip_real)


# --------------------------------------------------------------------------- #
# Event loop — session-scoped so async session-scoped fixtures share state.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --------------------------------------------------------------------------- #
# LLM / embedding stubs (autouse). Marker ``real_llm`` opts out.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def stub_llms(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every per-agent LLM getter with a deterministic fake.

    Getters are patched in the *consuming* module (they are imported by name at
    module load), not in tools.llm_client.
    """
    if "real_llm" in request.keywords and RUN_REAL_LLM:
        return
    try:
        from tests._fakes.fake_chat import make_fake_chat
    except Exception:  # pragma: no cover - fakes not written yet during scaffold
        return

    targets = {
        "agents.intent_router": ["get_router_llm"],
        "agents.tutoring_agent": ["get_tutor_llm"],
        "agents.quiz_agent": ["get_quiz_llm"],
        "agents.problem_generator": ["get_quiz_llm"],
        "agents.scoring_agent": ["get_scoring_llm"],
        "agents.quiz_analyzer": ["get_scoring_llm"],
        "agents.recommendation_agent": ["get_recommendation_llm"],
        "agents.reflection_agent": ["get_router_llm"],
        "accessibility.simplifier": ["get_quiz_llm"],
        "accessibility.narration": ["get_tutor_llm"],
        "analytics.insights": ["get_recommendation_llm"],
    }
    import importlib

    for mod_name, getters in targets.items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for getter in getters:
            if hasattr(mod, getter):
                role = getter.replace("get_", "").replace("_llm", "")
                monkeypatch.setattr(mod, getter, lambda *a, _r=role, **k: make_fake_chat(_r))


@pytest.fixture(autouse=True)
def stub_embeddings(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "real_llm" in request.keywords and RUN_REAL_LLM:
        return
    try:
        from tests._fakes.fake_embeddings import fake_embed_text
    except Exception:  # pragma: no cover
        return
    import importlib

    for mod_name in ("rag.embeddings", "rag.retriever", "agents.scoring_agent", "rag.ingestion"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if hasattr(mod, "embed_text"):
            monkeypatch.setattr(mod, "embed_text", fake_embed_text)


# --------------------------------------------------------------------------- #
# Database — real Postgres from docker-compose.test.yml (Stage 3+).
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
async def db_engine():  # type: ignore[no-untyped-def]
    """Initialise the process-wide engine + ensure the test schema exists."""
    from database.session import close_db, get_engine, init_db

    await init_db()
    # Build ORM schema + curriculum_chunks DDL (idempotent).
    try:
        from sqlalchemy import text

        from database.models import Base
        from scripts.create_test_db import _DDL  # type: ignore[attr-defined]

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in _DDL:
                await conn.execute(text(stmt))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"test database unavailable: {exc}")
    yield get_engine()
    await close_db()


@pytest.fixture
async def db_session(db_engine):  # type: ignore[no-untyped-def]
    """Function-scoped session wrapped in a rolled-back SAVEPOINT."""
    from sqlalchemy.ext.asyncio import AsyncSession

    conn = await db_engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest.fixture(scope="session")
async def seeded_curriculum(db_engine):  # type: ignore[no-untyped-def]
    """Run scripts.seed_curriculum once for the session."""
    try:
        from scripts.seed_curriculum import main as seed_main  # type: ignore[attr-defined]

        await seed_main()
    except Exception:  # pragma: no cover - seeding is best-effort for scaffold
        pass
    yield


# --------------------------------------------------------------------------- #
# Redis — real Redis from docker-compose.test.yml.
# --------------------------------------------------------------------------- #
@pytest.fixture
async def redis_client() -> AsyncIterator[object]:
    from memory.short_term import close_redis, get_redis

    client = await get_redis()
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await close_redis()


# --------------------------------------------------------------------------- #
# HTTP/WS client against the real `api` container (Stage 4-9).
#
# kodmod-ai runs entirely in Docker (postgres, redis, llm-stub, api — see
# docker/docker-compose.test.yml). Test *scripts* run natively on the host
# (PowerShell/bash), never inside a container, and talk to the `api` service
# over the port it publishes. Bring the stack up first:
#
#   docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d --build api
#
# `KODMOD_API_BASE_URL` overrides the default http://localhost:8000 (matches
# compose's API_HOST_PORT). The container gets its own LLM/embedding stub via
# env (KODMOD_LLM_PROVIDER=vllm -> llm-stub) — the stub_llms/stub_embeddings
# fixtures above only matter for Stage 1/3, which call Python functions
# directly in the host pytest process, not through the container.
# --------------------------------------------------------------------------- #
API_BASE_URL = os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return API_BASE_URL


@pytest.fixture
async def client(api_base_url: str):  # type: ignore[no-untyped-def]
    """Real HTTP client against the containerized api. Requires the stack up."""
    import httpx

    async with httpx.AsyncClient(base_url=api_base_url, timeout=30.0) as c:
        yield c


@pytest.fixture
def ws_url(api_base_url: str) -> str:
    """ws://localhost:8000/ws/voice — real WebSocket to the containerized api."""
    return api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"


@pytest.fixture(scope="session")
def fastapi_app():  # type: ignore[no-untyped-def]
    """Static introspection only (Stage 2 contract): route/schema checks without
    running the lifespan or needing any container up. Do NOT use this for
    behavioral testing — use `client` against the real container for that.
    """
    from api.main import app as fastapi_app

    return fastapi_app


# --------------------------------------------------------------------------- #
# Auth helpers.
# --------------------------------------------------------------------------- #
def _make_token(sub: uuid.UUID | str, role: str, *, ttl_s: int = 3600) -> str:
    import time

    import jwt as pyjwt

    from config.settings import settings

    now = int(time.time())
    return pyjwt.encode(
        {"sub": str(sub), "role": role, "iat": now, "exp": now + ttl_s},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


@pytest.fixture
def make_token():  # type: ignore[no-untyped-def]
    return _make_token


@pytest.fixture
def auth_headers():  # type: ignore[no-untyped-def]
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
async def student_factory(db_session):  # type: ignore[no-untyped-def]
    """Insert an ORM Student and return (student, token)."""
    created: list = []

    async def _make(**overrides):  # type: ignore[no-untyped-def]
        from database.models import Student

        data = {
            "id": overrides.pop("id", uuid.uuid4()),
            "full_name": overrides.pop("full_name", "Siswa Uji"),
            "accessibility_profile": overrides.pop("accessibility_profile", "blind"),
            "preferred_language": overrides.pop("preferred_language", "id"),
        }
        data.update(overrides)
        student = Student(**data)
        db_session.add(student)
        await db_session.flush()
        created.append(student)
        return student, _make_token(student.id, "student")

    return _make


@pytest.fixture
async def teacher_factory(db_session):  # type: ignore[no-untyped-def]
    async def _make(**overrides):  # type: ignore[no-untyped-def]
        from database.models import Teacher

        data = {"id": overrides.pop("id", uuid.uuid4()), "full_name": "Guru Uji"}
        data.update(overrides)
        teacher = Teacher(**data)
        db_session.add(teacher)
        await db_session.flush()
        return teacher, _make_token(teacher.id, "teacher")

    return _make


# --------------------------------------------------------------------------- #
# Graph fixtures.
# --------------------------------------------------------------------------- #
@pytest.fixture
async def graph():  # type: ignore[no-untyped-def]
    from graphs.main_graph import build_kodmod_graph

    return await build_kodmod_graph(checkpointer=None)


@pytest.fixture
async def checkpointed_graph(db_engine):  # type: ignore[no-untyped-def]
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from config.settings import settings
    from graphs.main_graph import build_kodmod_graph

    async with AsyncPostgresSaver.from_conn_string(settings.LANGGRAPH_DB_URI) as cp:
        await cp.setup()
        yield await build_kodmod_graph(checkpointer=cp)
