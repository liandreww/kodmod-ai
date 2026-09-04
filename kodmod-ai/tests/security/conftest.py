"""Stage 9 (dynamic security) fixtures — real HTTP against the host ``api``.

Spec: docs/testplan/09-security.md. Same host-``api`` model as Stage 4-7: the
process under test reads the shared Postgres, so factories commit and clean up.

``_jwt_attacks`` (sibling module) assembles the malicious tokens.
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

pytestmark = [pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def _api_up(api_base_url: str) -> None:
    """Skip only the tests that need the live api (in-process SSRF cases don't)."""
    try:
        httpx.get(f"{api_base_url}/live", timeout=5.0).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"api not reachable at {api_base_url}: {exc}")


@pytest.fixture
async def client(api_base_url: str, _api_up: None):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(base_url=api_base_url, timeout=30.0) as c:
        yield c


def _token(sub, role: str = "student", *, ttl_s: int = 3600, secret: str | None = None) -> str:
    import jwt as pyjwt

    from config.settings import settings

    now = int(time.time())
    return pyjwt.encode(
        {"sub": str(sub), "role": role, "iat": now, "exp": now + ttl_s},
        secret or settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


@pytest.fixture
def make_token():  # type: ignore[no-untyped-def]
    return _token


@pytest.fixture
def auth_headers():  # type: ignore[no-untyped-def]
    return lambda tok: {"Authorization": f"Bearer {tok}"}


@pytest.fixture
async def db_cleanup():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    _children = (
        "analytics_reports",
        "recommendations",
        "misconceptions",
        "mastery_scores",
        "quiz_sessions",
    )
    await init_db()
    trash: list[tuple[str, str]] = []
    yield trash
    if not trash:
        return
    async with async_session() as s:
        for table, _id in reversed(trash):
            if table == "students":
                for child in _children:
                    try:
                        await s.execute(
                            text(f"DELETE FROM {child} WHERE student_id = CAST(:id AS uuid)"),
                            {"id": _id},
                        )
                    except Exception:
                        pass
            try:
                await s.execute(
                    text(f"DELETE FROM {table} WHERE id = CAST(:id AS uuid)"), {"id": _id}
                )
            except Exception:
                pass


@pytest.fixture
async def student_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Student
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        sid = over.pop("id", uuid.uuid4())
        async with async_session() as s:
            row = Student(
                id=sid,
                full_name=over.pop("full_name", "Siswa Sec"),
                accessibility_profile="blind",
                preferred_language=over.pop("preferred_language", "id"),
            )
            s.add(row)
            await s.flush()
            s.expunge(row)
        db_cleanup.append(("students", str(sid)))
        return row, _token(sid, "student")

    return _make


@pytest.fixture
async def teacher_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Teacher
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        tid = over.pop("id", uuid.uuid4())
        async with async_session() as s:
            s.add(
                Teacher(
                    id=tid,
                    full_name=over.pop("full_name", "Guru Sec"),
                    email=over.pop("email", f"guru-{uuid.uuid4().hex[:8]}@example.test"),
                )
            )
        db_cleanup.append(("teachers", str(tid)))
        return tid, _token(tid, "teacher")

    return _make


@pytest.fixture
async def concept_ids():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    async with async_session() as s:
        rows = (await s.execute(text("SELECT slug, id FROM concepts"))).all()
    return {slug: str(cid) for slug, cid in rows}


@pytest.fixture
async def curriculum_chunk_count():  # type: ignore[no-untyped-def]
    """Callable -> current row count of curriculum_chunks (for 'table intact' asserts)."""
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()

    async def _count() -> int:
        async with async_session() as s:
            return int(
                (await s.execute(text("SELECT count(*) FROM curriculum_chunks"))).scalar_one()
            )

    return _count
