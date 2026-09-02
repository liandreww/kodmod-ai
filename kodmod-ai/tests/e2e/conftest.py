"""Stage 6 (E2E) fixtures — real HTTP journeys against the containerized api."""

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


@pytest.fixture(scope="session", autouse=True)
def _require_stack(api_base_url):  # type: ignore[no-untyped-def]
    try:
        httpx.get(f"{api_base_url}/live", timeout=5.0).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"api container not reachable: {exc}")


@pytest.fixture
async def client(api_base_url):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(base_url=api_base_url, timeout=45.0) as c:
        yield c


def _token(sub, role: str) -> str:
    import jwt as pyjwt

    from config.settings import settings

    now = int(time.time())
    return pyjwt.encode(
        {"sub": str(sub), "role": role, "iat": now, "exp": now + 3600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


@pytest.fixture
def auth_headers():  # type: ignore[no-untyped-def]
    return lambda tok: {"Authorization": f"Bearer {tok}"}


@pytest.fixture
async def db_cleanup():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    trash: list[tuple[str, str]] = []
    yield trash
    if not trash:
        return

    async def _try(sql: str, params: dict) -> None:
        # fresh session per statement so a failure never poisons the next delete
        try:
            async with async_session() as s:
                await s.execute(text(sql), params)
        except Exception:
            pass

    _by_student = (
        "mastery_scores",
        "misconceptions",
        "recommendations",
        "analytics_reports",
        "interaction_logs",
        "learning_sessions",
    )
    for table, _id in reversed(trash):
        if table == "students":
            await _try(
                "DELETE FROM quiz_attempts WHERE quiz_session_id IN "
                "(SELECT id FROM quiz_sessions WHERE student_id = CAST(:id AS uuid))",
                {"id": _id},
            )
            await _try(
                "DELETE FROM quiz_questions WHERE quiz_session_id IN "
                "(SELECT id FROM quiz_sessions WHERE student_id = CAST(:id AS uuid))",
                {"id": _id},
            )
            await _try(
                "DELETE FROM quiz_sessions WHERE student_id = CAST(:id AS uuid)", {"id": _id}
            )
            for child in _by_student:
                await _try(f"DELETE FROM {child} WHERE student_id = CAST(:id AS uuid)", {"id": _id})
        await _try(f"DELETE FROM {table} WHERE id = CAST(:id AS uuid)", {"id": _id})


@pytest.fixture
async def student_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Student
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        sid = over.pop("id", uuid.uuid4())
        async with async_session() as s:
            s.add(
                Student(
                    id=sid,
                    full_name=over.pop("full_name", "Siswa E2E"),
                    accessibility_profile="blind",
                    preferred_language=over.pop("preferred_language", "id"),
                )
            )
        db_cleanup.append(("students", str(sid)))
        return sid, _token(sid, "student")

    return _make


@pytest.fixture
async def teacher_factory(db_cleanup):  # type: ignore[no-untyped-def]
    from database.models import Teacher
    from database.session import async_session

    async def _make(**over):  # type: ignore[no-untyped-def]
        tid = over.pop("id", uuid.uuid4())
        async with async_session() as s:
            s.add(Teacher(id=tid, full_name="Guru E2E", email=f"g-{uuid.uuid4().hex[:8]}@x.test"))
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
async def seed_mastery():  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()

    async def _seed(student_id, mapping: dict) -> None:
        async with async_session() as s:
            for cid, m in mapping.items():
                await s.execute(
                    text(
                        "INSERT INTO mastery_scores (id, student_id, concept_id, mastery, "
                        "confidence, n_attempts, last_seen) VALUES (gen_random_uuid(), "
                        "CAST(:sid AS uuid), CAST(:cid AS uuid), :m, 0.6, 3, :ls)"
                    ),
                    {"sid": str(student_id), "cid": str(cid), "m": m, "ls": datetime.now(UTC)},
                )

    return _seed
