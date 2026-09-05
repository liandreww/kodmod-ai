"""Stage 3 (integration) fixtures — real Postgres + Redis, stubbed LLM/embeddings.

Node / store / memory code opens its own ``async_session()`` (not the
SAVEPOINT-wrapped ``db_session`` from the top-level conftest), so isolation here
is by explicit cleanup: ``clean_db`` DELETEs every volatile table before and
after each test. ``db_engine`` (session-scoped, from the root conftest) has
already run ``init_db()`` + created the ORM schema.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration]

# Volatile tables, ordered so FK children are cleared before parents.
_VOLATILE = [
    "quiz_attempts",
    "quiz_questions",
    "quiz_sessions",
    "interaction_logs",
    "learning_sessions",
    "misconceptions",
    "mastery_scores",
    "recommendations",
    "analytics_reports",
    "curriculum_chunks",
    "exercises",
    "documents",
    "invitation_codes",
    "users",
]


async def _wipe() -> None:
    from sqlalchemy import text

    from database.session import async_session

    async with async_session() as s:
        for tbl in _VOLATILE:
            await s.execute(text(f"DELETE FROM {tbl}"))


@pytest.fixture(autouse=True)
def stub_reranker(request, monkeypatch):  # type: ignore[no-untyped-def]
    """Force the cross-encoder reranker into its graceful bi-encoder fallback.

    The real ``rag.reranker._load_model`` constructs ``CrossEncoder(...)`` which
    downloads ~600 MB from HuggingFace — unacceptable in the suite. ``real_llm``
    tests opt out.
    """
    if "real_llm" in request.keywords:
        return
    try:
        from rag import reranker
    except Exception:
        return
    reranker._load_model.cache_clear()
    monkeypatch.setattr(reranker, "_load_model", lambda: None)


@pytest.fixture
async def clean_db(db_engine):  # type: ignore[no-untyped-def]
    await _wipe()
    yield
    await _wipe()


@pytest.fixture
async def concept_ids(db_engine):  # type: ignore[no-untyped-def]
    """slug -> concept UUID, from the seeded curriculum (session-stable)."""
    from sqlalchemy import text

    from database.session import async_session

    async with async_session() as s:
        rows = (await s.execute(text("SELECT slug, id FROM concepts"))).all()
    return {slug: cid for slug, cid in rows}


@pytest.fixture
async def make_student(clean_db):  # type: ignore[no-untyped-def]
    """Factory: insert a student `users` row in its own committed session."""
    from api.security import hash_password
    from database.models import User
    from database.session import async_session
    from tests.conftest import TEST_PASSWORD

    async def _make(**over):  # type: ignore[no-untyped-def]
        uid = over.pop("id", uuid.uuid4())
        data = dict(
            id=uid,
            username=over.pop("username", f"siswa-{uid.hex[:8]}"),
            password_hash=hash_password(TEST_PASSWORD),
            role="student",
            full_name=over.pop("full_name", "Siswa Uji"),
            accessibility_profile=over.pop("accessibility_profile", "blind"),
            preferred_language=over.pop("preferred_language", "id"),
        )
        data.update(over)
        async with async_session() as s:
            row = User(**data)
            s.add(row)
            await s.flush()
            s.expunge(row)
        return row

    return _make


@pytest.fixture
async def redis_client():  # type: ignore[no-untyped-def]
    """Function-scoped Redis client with flushdb isolation.

    Overrides the root fixture: on Windows the ProactorEventLoop + redis-py
    ``pool.aclose()`` combo raises "Future attached to a different loop" during
    teardown, so we keep the cached pool alive across tests and only flush.
    """
    from memory.short_term import get_redis

    client = await get_redis()
    await client.flushdb()
    try:
        yield client
    finally:
        try:
            await client.flushdb()
        except Exception:
            pass


@pytest.fixture
async def seed_mastery(clean_db):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from sqlalchemy import text

    from database.session import async_session

    async def _seed(student_id, mapping: dict, *, n_attempts: int = 1, confidence: float = 0.5):  # type: ignore[no-untyped-def]
        async with async_session() as s:
            for cid, mastery in mapping.items():
                await s.execute(
                    text(
                        "INSERT INTO mastery_scores "
                        "(id, student_id, concept_id, mastery, confidence, n_attempts, last_seen) "
                        "VALUES (gen_random_uuid(), CAST(:sid AS uuid), CAST(:cid AS uuid), "
                        ":m, :c, :n, :ls)"
                    ),
                    {
                        "sid": str(student_id),
                        "cid": str(cid),
                        "m": mastery,
                        "c": confidence,
                        "n": n_attempts,
                        "ls": datetime.now(UTC),
                    },
                )

    return _seed
