"""Stage 4 (API) fixtures — real HTTP against the host ``api`` process.

The host ``api`` (``python -m scripts.serve_test_api``) reads the SAME Postgres
(``localhost:5433``) as these fixtures, so seeding here must **commit** (unlike
the root ``student_factory`` which rolls its SAVEPOINT back). Everything created
is tracked and deleted on teardown.

Requires the infra + host api up (or run via scripts/run_tests.{ps1,sh}):
    docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub
    python -m scripts.init_test_db
    python -m scripts.serve_test_api
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

    # Learner-owned tables all cascade from users.id now, but they are deleted
    # explicitly anyway so a broken cascade surfaces as a test failure rather
    # than as rows quietly surviving between runs.
    _user_children = (
        "analytics_reports",
        "recommendations",
        "misconceptions",
        "mastery_scores",
        "quiz_sessions",
        "learning_sessions",
    )

    await init_db()
    trash: list[tuple[str, str]] = []
    yield trash
    if trash:
        async with async_session() as s:
            for table, _id in reversed(trash):
                if table == "users":
                    for child in _user_children:
                        await s.execute(
                            text(f"DELETE FROM {child} WHERE student_id = :id"), {"id": _id}
                        )
                await s.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": _id})


_DEFAULT_NAMES = {"student": "Siswa Uji", "teacher": "Guru Uji", "admin": "Admin Uji"}


@pytest.fixture
async def user_factory(db_cleanup):  # type: ignore[no-untyped-def]
    """Commit a real `users` row (the host api reads the same DB) plus its token."""
    from api.security import hash_password
    from database.models import User
    from database.session import async_session
    from tests.conftest import TEST_PASSWORD

    async def _make(role: str = "student", **over):  # type: ignore[no-untyped-def]
        uid = over.pop("id", uuid.uuid4())
        data = dict(
            id=uid,
            username=over.pop("username", f"{role}-{uid.hex[:8]}"),
            password_hash=hash_password(TEST_PASSWORD),
            role=role,
            full_name=over.pop("full_name", _DEFAULT_NAMES.get(role, "Pengguna Uji")),
            accessibility_profile=over.pop("accessibility_profile", "blind"),
            preferred_language=over.pop("preferred_language", "id"),
        )
        data.update(over)
        async with async_session() as s:
            row = User(**data)
            s.add(row)
            await s.flush()
            s.expunge(row)
        db_cleanup.append(("users", str(uid)))
        return row, _token(uid, role)

    return _make


@pytest.fixture
async def student_factory(user_factory):  # type: ignore[no-untyped-def]
    async def _make(**over):  # type: ignore[no-untyped-def]
        return await user_factory("student", **over)

    return _make


@pytest.fixture
async def teacher_factory(user_factory):  # type: ignore[no-untyped-def]
    async def _make(**over):  # type: ignore[no-untyped-def]
        over.pop("email", None)  # accounts are identified by username now
        return await user_factory("teacher", **over)

    return _make


@pytest.fixture
async def admin_factory(user_factory):  # type: ignore[no-untyped-def]
    async def _make(**over):  # type: ignore[no-untyped-def]
        return await user_factory("admin", **over)

    return _make


@pytest.fixture
async def subject_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Subject
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        sid = over.pop("id", uuid.uuid4())
        data = dict(id=sid, name=over.pop("name", f"Mapel {sid.hex[:6]}"))
        data.update(over)
        async with async_session() as s:
            row = Subject(**data)
            s.add(row)
            await s.flush()
            s.expunge(row)
        db_cleanup.append(("subjects", str(sid)))
        return row

    return _make


@pytest.fixture
async def concept_ids():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    async with async_session() as s:
        rows = (await s.execute(text("SELECT slug, id FROM concepts"))).all()
    return {slug: str(cid) for slug, cid in rows}
