"""Shared pytest fixtures for the KODMOD test suite.

Stage map (see docs/testplan/):
  0 static      1 unit        2 contract    3 integration
  4 api         5 ws          6 e2e         9 security

Only the infra runs in Docker (docker/docker-compose.test.yml: postgres, redis,
llm-stub). `db-init` and `api` run natively on the host, as do the test SCRIPTS:
  * Stage 1 (unit) needs no service at all.
  * Stage 3 (integration) calls Python functions directly in this process and
    talks to Postgres/Redis over their published ports.
  * Stage 4+ (api/ws/e2e/security) talk to the host `api` process
    (`python -m scripts.serve_test_api`) over HTTP/WS — see the `client`/`ws_url`
    fixtures below. `scripts/run_tests.{ps1,sh}` start/stop it for you.

Environment is forced to ``test`` BEFORE any project import so the cached
``config.settings`` singleton picks up test values. For Stage 1/3, LLM and
embedding calls made *in this process* are stubbed by autouse fixtures unless
a test is marked ``real_llm``. For Stage 4+, the host `api` points
``OPENAI_BASE_URL`` at the llm-stub service instead (scripts/serve_test_api).
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
os.environ.setdefault("OPENAI_API_KEY", "test-key")
for _role in ("ROUTER", "TUTOR", "QUIZ", "SCORING", "RECOMMENDATION", "REFLECTION"):
    os.environ.setdefault(f"LLM_{_role}_MODEL", f"stub-{_role.lower()}")
os.environ.setdefault("DB_NAME", "kodmod_test")
os.environ.setdefault("DB_HOST", os.environ.get("DB_HOST", "localhost"))
os.environ.setdefault("DB_PORT", os.environ.get("DB_PORT", "5433"))
os.environ.setdefault("REDIS_HOST", os.environ.get("REDIS_HOST", "localhost"))
os.environ.setdefault("REDIS_PORT", os.environ.get("REDIS_PORT", "6380"))
os.environ.setdefault("EMBEDDING_DIM", "1536")
os.environ.setdefault("UPLOAD_DIR", os.path.join(os.getcwd(), ".runtime", "uploads"))
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod-0123456789abcdef")

RUN_REAL_LLM = os.getenv("KODMOD_RUN_REAL_LLM") == "1"

# Fixed UUIDs — see docs/testplan/test-data.md
STUDENT_BLIND = uuid.UUID("11111111-1111-1111-1111-111111111111")
STUDENT_LOWVISION = uuid.UUID("11111111-1111-1111-1111-111111111112")
STUDENT_STRONG = uuid.UUID("11111111-1111-1111-1111-111111111113")
TEACHER_A = uuid.UUID("22222222-2222-2222-2222-222222222221")
ADMIN_A = uuid.UUID("33333333-3333-3333-3333-333333333331")

# Every generated account shares this password so tests can log in for real.
TEST_PASSWORD = "test-password-123"


# --------------------------------------------------------------------------- #
# Markers are registered in pyproject.toml [tool.pytest.ini_options].markers
# (single source of truth — keep the two lists in sync if either changes):
#   static, unit, contract, integration, api, ws, e2e, security,
#   real_llm, slow, db, redis, known_bug
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
_LLM_GETTERS = (
    "get_router_llm",
    "get_tutor_llm",
    "get_quiz_llm",
    "get_scoring_llm",
    "get_recommendation_llm",
    "get_reflection_llm",
)

_LLM_CONSUMERS = (
    "tools.llm_client",
    "agents.intent_router",
    "agents.tutoring_agent",
    "agents.quiz_agent",
    "agents.problem_generator",
    "agents.scoring_agent",
    "agents.quiz_analyzer",
    "agents.recommendation_agent",
    "agents.reflection_agent",
    "accessibility.simplifier",
    "accessibility.narration",
    "analytics.insights",
)


@pytest.fixture(autouse=True)
def stub_llms(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every LLM role getter with a deterministic fake.

    Agent modules do `from tools.llm_client import get_tutor_llm`, binding the
    getter at import time, so patching `tools.llm_client` alone would not reach
    them. Every consuming module is patched, plus the source of truth.
    """
    if "real_llm" in request.keywords and RUN_REAL_LLM:
        return
    # Tests of the client itself must see the real getters.
    if "no_llm_stub" in request.keywords:
        return
    try:
        from tests._fakes.fake_chat import make_fake_chat
    except Exception:  # pragma: no cover - fakes not written yet during scaffold
        return

    import importlib

    for mod_name in _LLM_CONSUMERS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for getter in _LLM_GETTERS:
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
    try:
        from sqlalchemy import text

        from database.models import Base
        from scripts.create_test_db import _EXTENSIONS

        engine = get_engine()
        async with engine.begin() as conn:
            for stmt in _EXTENSIONS:
                await conn.execute(text(stmt))
            await conn.run_sync(Base.metadata.create_all)
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
# HTTP/WS client against the real `api` process (Stage 4-9).
#
# Only the infra runs in Docker (postgres, redis, llm-stub, see
# docker/docker-compose.test.yml). `db-init` and `api` run natively on the host.
# Test *scripts* run natively too and talk to the host `api` over :8000.
# Bring it up first (or just let scripts/run_tests.{ps1,sh} do it):
#
#   docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub
#   python -m scripts.init_test_db
#   python -m scripts.serve_test_api
#
# `KODMOD_API_BASE_URL` overrides the default http://localhost:8000. The host
# `api` gets its stub via OPENAI_BASE_URL, set by scripts/serve_test_api to
# http://localhost:8099/v1. The stub_llms/stub_embeddings fixtures above only
# matter for Stage 1/3, which call Python functions in the pytest process.
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
    """ws://localhost:8000/ws/chat — real WebSocket to the running api."""
    return api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/chat"


@pytest.fixture(scope="session")
def fastapi_app():  # type: ignore[no-untyped-def]
    """Static introspection only (Stage 2 contract): route/schema checks without
    running the lifespan or needing any container up. Do NOT use this for
    behavioral testing; use `client` against the running api for that.
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


_DEFAULT_NAMES = {"student": "Siswa Uji", "teacher": "Guru Uji", "admin": "Admin Uji"}


@pytest.fixture
async def user_factory(db_session):  # type: ignore[no-untyped-def]
    """Insert a real `users` row and return (user, bearer_token).

    Every account gets `TEST_PASSWORD`, so a test can either use the token
    directly or go through POST /auth/login like a real client would.
    """

    async def _make(role: str = "student", **overrides):  # type: ignore[no-untyped-def]
        from api.security import hash_password
        from database.models import User

        uid = overrides.pop("id", uuid.uuid4())
        data = {
            "id": uid,
            "username": overrides.pop("username", f"{role}-{uid.hex[:8]}"),
            "password_hash": hash_password(TEST_PASSWORD),
            "role": role,
            "full_name": overrides.pop("full_name", _DEFAULT_NAMES.get(role, "Pengguna Uji")),
        }
        data.update(overrides)
        user = User(**data)
        db_session.add(user)
        await db_session.flush()
        return user, _make_token(user.id, role)

    return _make


@pytest.fixture
async def student_factory(user_factory):  # type: ignore[no-untyped-def]
    async def _make(**overrides):  # type: ignore[no-untyped-def]
        return await user_factory("student", **overrides)

    return _make


@pytest.fixture
async def teacher_factory(user_factory):  # type: ignore[no-untyped-def]
    async def _make(**overrides):  # type: ignore[no-untyped-def]
        return await user_factory("teacher", **overrides)

    return _make


@pytest.fixture
async def admin_factory(user_factory):  # type: ignore[no-untyped-def]
    async def _make(**overrides):  # type: ignore[no-untyped-def]
        return await user_factory("admin", **overrides)

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
