"""Stage 5 (WebSocket) fixtures — real WS to the containerized ``api`` service.

Mirrors tests/api/conftest.py: committing student/teacher factories (the
container reads the same Postgres) + a ``ws_connect`` helper built on httpx-ws.
"""

from __future__ import annotations

import contextlib
import os
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from httpx_ws import WebSocketUpgradeError, aconnect_ws

pytestmark = [pytest.mark.asyncio(loop_scope="session")]

WS_TIMEOUT = 5.0


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def ws_base_url(api_base_url: str) -> str:
    return api_base_url.replace("http://", "ws://").replace("https://", "wss://")


@pytest.fixture(scope="session", autouse=True)
def _require_stack(api_base_url):  # type: ignore[no-untyped-def]
    try:
        httpx.get(f"{api_base_url}/live", timeout=5.0).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"api container not reachable at {api_base_url}: {exc}")


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
async def db_cleanup():  # type: ignore[no-untyped-def]
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
            full_name=over.pop("full_name", "Siswa WS"),
            accessibility_profile="blind",
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
        tid = over.pop("id", uuid.uuid4())
        async with async_session() as s:
            s.add(Teacher(id=tid, full_name="Guru WS", email=f"g-{uuid.uuid4().hex[:8]}@x.test"))
        db_cleanup.append(("teachers", str(tid)))
        return tid, _token(tid, "teacher")

    return _make


@pytest.fixture
def ws_connect(ws_base_url):  # type: ignore[no-untyped-def]
    """async context manager: ws_connect(token=..., raw_url=...) -> session.

    Raises httpx_ws.WebSocketUpgradeError if the server rejects the handshake
    (authenticate_ws closes before accept -> HTTP 403 on the upgrade).
    """

    @contextlib.asynccontextmanager
    async def _connect(
        *, token: str | None = None, path: str = "/ws/voice", headers: dict | None = None
    ) -> AsyncIterator[object]:
        url = f"{ws_base_url}{path}"
        if token is not None:
            url += f"?token={token}"
        async with httpx.AsyncClient() as client:
            async with aconnect_ws(url, client, headers=headers or {}) as ws:
                yield ws

    return _connect


@pytest.fixture
def upgrade_error():  # type: ignore[no-untyped-def]
    return WebSocketUpgradeError
