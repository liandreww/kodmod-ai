"""Stage 3 §1 — DB layer: database/session.py, scripts/create_test_db.py, ORM schema.

Spec: docs/testplan/03-integration.md §1 (KM-INT-001..011).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]


# --------------------------------------------------------------------------- #
# KM-INT-001 — init_db smoke + NullPool has no sizing kwargs  (bug 2, #22)
# --------------------------------------------------------------------------- #
async def test_km_int_001_init_db_smoke(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database.session import _make_engine, get_engine

    async with get_engine().connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1

    # _make_engine must not pass pool_size/max_overflow when NullPool is selected
    # (ENV=test) — SQLAlchemy raises TypeError otherwise (#22).
    eng = _make_engine()
    try:
        assert isinstance(eng.pool, NullPool)
    finally:
        await eng.dispose()


# --------------------------------------------------------------------------- #
# KM-INT-002 — init_db idempotent
# --------------------------------------------------------------------------- #
async def test_km_int_002_init_db_idempotent(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database import session as m

    first = m.get_engine()
    await m.init_db()
    assert m.get_engine() is first


# --------------------------------------------------------------------------- #
# KM-INT-003 — NullPool when ENV=test
# --------------------------------------------------------------------------- #
async def test_km_int_003_null_pool_in_test(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database.session import get_engine

    assert isinstance(get_engine().pool, NullPool)


# --------------------------------------------------------------------------- #
# KM-INT-004 — every ORM table exists in the DB
# --------------------------------------------------------------------------- #
async def test_km_int_004_all_orm_tables_present(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database.models import Base
    from database.session import async_session

    async with async_session() as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                    )
                )
            )
            .scalars()
            .all()
        )
    present = set(rows)
    missing = set(Base.metadata.tables) - present
    assert not missing, f"ORM tables missing from DB: {missing}"


# --------------------------------------------------------------------------- #
# KM-INT-005 / 006 — curriculum_chunks DDL + extensions
# --------------------------------------------------------------------------- #
async def test_km_int_005_curriculum_chunks_ddl(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session

    async with async_session() as s:
        dims = (
            await s.execute(
                text(
                    "SELECT a.atttypmod FROM pg_attribute a "
                    "JOIN pg_class c ON c.oid = a.attrelid "
                    "WHERE c.relname='curriculum_chunks' AND a.attname='embedding'"
                )
            )
        ).scalar_one()
        idx = (
            (
                await s.execute(
                    text("SELECT indexdef FROM pg_indexes WHERE tablename='curriculum_chunks'")
                )
            )
            .scalars()
            .all()
        )
    assert dims == 1024  # vector(1024)
    joined = " ".join(idx).lower()
    assert "hnsw" in joined and "vector_cosine_ops" in joined
    assert any("concept_id" in d for d in idx)
    assert any("source" in d for d in idx)


async def test_km_int_006_extensions_enabled(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session

    async with async_session() as s:
        exts = (await s.execute(text("SELECT extname FROM pg_extension"))).scalars().all()
    assert {"vector", "pgcrypto"} <= set(exts)


# --------------------------------------------------------------------------- #
# KM-INT-007 — ORM columns match reality (not schema.sql's names)
# --------------------------------------------------------------------------- #
async def test_km_int_007_orm_columns_match_db(db_engine) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session

    async def cols(table: str) -> set[str]:
        async with async_session() as s:
            return set(
                (
                    await s.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_name=:t"
                        ),
                        {"t": table},
                    )
                )
                .scalars()
                .all()
            )

    mastery = await cols("mastery_scores")
    assert {"mastery", "confidence", "n_attempts", "last_seen"} <= mastery
    # schema.sql legacy names must NOT be what the DB has
    assert "score" not in mastery and "last_practiced" not in mastery

    students = await cols("students")
    assert {
        "full_name",
        "accessibility_profile",
        "preferred_language",
        "voice_settings",
    } <= students
    assert "display_name" not in students


# --------------------------------------------------------------------------- #
# KM-INT-008 — async_session commits on clean exit, rolls back on error
# --------------------------------------------------------------------------- #
async def test_km_int_008_async_session_commit_and_rollback(db_engine, make_student) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from database.models import Student
    from database.session import async_session

    sid = uuid.uuid4()
    async with async_session() as s:
        s.add(Student(id=sid, full_name="Commit OK"))
    async with async_session() as s:
        assert await s.get(Student, sid) is not None

    sid2 = uuid.uuid4()
    with pytest.raises(RuntimeError):
        async with async_session() as s:
            s.add(Student(id=sid2, full_name="Rollback"))
            await s.flush()
            raise RuntimeError("boom")
    async with async_session() as s:
        assert await s.get(Student, sid2) is None


# --------------------------------------------------------------------------- #
# KM-INT-009 — get_db dependency generator commits/rolls back
# --------------------------------------------------------------------------- #
async def test_km_int_009_get_db_generator(db_engine, make_student) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from database.models import Student
    from database.session import async_session, get_db

    sid = uuid.uuid4()
    gen = get_db()
    s = await gen.__anext__()
    s.add(Student(id=sid, full_name="via get_db"))
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()  # clean close -> commit
    async with async_session() as chk:
        assert await chk.get(Student, sid) is not None


# --------------------------------------------------------------------------- #
# KM-INT-010 — close_db disposes + resets globals (isolated, monkeypatched)
# --------------------------------------------------------------------------- #
async def test_km_int_010_close_db_resets_globals(db_engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from database import session as m

    throwaway = m._make_engine()
    monkeypatch.setattr(m, "_engine", throwaway)
    monkeypatch.setattr(m, "_session_factory", async_sessionmaker(throwaway))

    await m.close_db()
    assert m._engine is None
    assert m._session_factory is None
    # monkeypatch restores the real engine/factory at teardown


# --------------------------------------------------------------------------- #
# KM-INT-011 — the test schema is NOT bootstrapped from schema.sql
# --------------------------------------------------------------------------- #
def test_km_int_011_schema_sql_is_deprecated_for_tests() -> None:
    from pathlib import Path

    compose = (
        Path(__file__).resolve().parents[2] / "docker" / "docker-compose.test.yml"
    ).read_text(encoding="utf-8")
    # schema.sql may only appear inside an explanatory comment, never as a mount
    # into the postgres init dir. The test schema comes from scripts.create_test_db.
    for line in compose.splitlines():
        code = line.split("#", 1)[0]
        assert "schema.sql" not in code, f"schema.sql wired into compose: {line!r}"
    assert "docker-entrypoint-initdb.d" not in compose
    assert "create_test_db" in compose
