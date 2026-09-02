"""Stage 4 (API) fixtures — real HTTP against the containerized ``api`` service.

The ``api`` container reads the SAME Postgres (host 5433 -> container 5432), so
seeding fixtures here must **commit** (unlike the root ``student_factory`` which
rolls its SAVEPOINT back). Everything created is tracked and deleted on teardown.

Requires the stack up:
    docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d --build api
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

pytestmark = [pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture(scope="session")
def api_base_url() -> str:
    import os

    return os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session", autouse=True)
def _require_stack(api_base_url):  # type: ignore[no-untyped-def]
    try:
        r = httpx.get(f"{api_base_url}/live", timeout=5.0)
        r.raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"api container not reachable at {api_base_url}: {exc}")


@pytest.fixture
async def client(api_base_url):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(base_url=api_base_url, timeout=30.0) as c:
        yield c


def _token(sub, role: str, *, ttl_s: int = 3600, secret: str | None = None) -> str:
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
    """Collects (table, id) pairs to DELETE after the test."""
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    trash: list[tuple[str, str]] = []
    yield trash
    if trash:
        async with async_session() as s:
            for table, _id in reversed(trash):
                await s.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": _id})


@pytest.fixture
async def student_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Student
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        data = dict(
            id=over.pop("id", uuid.uuid4()),
            full_name=over.pop("full_name", "Siswa Uji"),
            accessibility_profile=over.pop("accessibility_profile", "blind"),
            preferred_language=over.pop("preferred_language", "id"),
        )
        data.update(over)
        async with async_session() as s:
            row = Student(**data)
            s.add(row)
            await s.flush()
            s.expunge(row)
        db_cleanup.append(("students", str(data["id"])))
        return row, _token(data["id"], "student")

    return _make


@pytest.fixture
async def teacher_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Teacher
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        data = dict(
            id=over.pop("id", uuid.uuid4()),
            full_name=over.pop("full_name", "Guru Uji"),
            email=over.pop("email", f"guru-{uuid.uuid4().hex[:8]}@example.test"),
        )
        data.update(over)
        async with async_session() as s:
            row = Teacher(**data)
            s.add(row)
            await s.flush()
            s.expunge(row)
        db_cleanup.append(("teachers", str(data["id"])))
        return row, _token(data["id"], "teacher")

    return _make


@pytest.fixture
async def concept_ids():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    async with async_session() as s:
        rows = (await s.execute(text("SELECT slug, id FROM concepts"))).all()
    return {slug: str(cid) for slug, cid in rows}
