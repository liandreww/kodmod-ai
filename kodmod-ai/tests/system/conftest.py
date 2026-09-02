"""Stage 7 (System / black-box) fixtures.

Driver runs natively on the host and controls the ``kodmod-test`` compose stack
via the ``docker`` CLI. If the stack is already up (the common local case) these
tests use it in place; they never ``down -v`` a stack they didn't start.
"""

from __future__ import annotations

import os
import subprocess
import time

import httpx
import pytest

API = os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")
API_CONTAINER = os.environ.get("KODMOD_API_CONTAINER", "kodmod-api-test")
PG_CONTAINER = os.environ.get("KODMOD_PG_CONTAINER", "kodmod-postgres-test")

pytestmark = [pytest.mark.system, pytest.mark.slow]


def docker(*args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


def wait_healthy(url: str = f"{API}/live", timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=3.0).status_code == 200:
                return
        except Exception as exc:  # pragma: no cover
            last = exc
        time.sleep(2.0)
    raise TimeoutError(f"{url} not healthy within {timeout}s (last: {last})")


@pytest.fixture(scope="session", autouse=True)
def compose_stack():  # type: ignore[no-untyped-def]
    try:
        docker("version", timeout=15)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"docker CLI unavailable: {exc}")
    ps = docker("ps", "--format", "{{.Names}}", check=False)
    if API_CONTAINER not in ps.stdout:
        pytest.skip(
            f"{API_CONTAINER} not running — bring the stack up: "
            "docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d --build api"
        )
    wait_healthy()
    yield


@pytest.fixture
def http() -> httpx.Client:
    with httpx.Client(base_url=API, timeout=30.0) as c:
        yield c


@pytest.fixture
def restart_api():  # type: ignore[no-untyped-def]
    def _restart() -> None:
        docker("restart", API_CONTAINER, timeout=120)
        wait_healthy()

    return _restart


@pytest.fixture
def make_e2e_student():  # type: ignore[no-untyped-def]
    """Insert a Student straight into the compose Postgres via docker exec psql,
    return (student_id, auth_headers). Sync — Stage 7 tests are sync.
    """
    import time as _t
    import uuid

    import jwt as pyjwt

    from config.settings import settings

    created: list[str] = []

    def _make() -> tuple[str, dict]:
        sid = str(uuid.uuid4())
        docker(
            "exec",
            PG_CONTAINER,
            "psql",
            "-U",
            "kodmod",
            "-d",
            "kodmod_test",
            "-c",
            f"INSERT INTO students (id, full_name, accessibility_profile, preferred_language) "
            f"VALUES ('{sid}', 'Siswa SYS', 'blind', 'id')",
        )
        created.append(sid)
        now = int(_t.time())
        tok = pyjwt.encode(
            {"sub": sid, "role": "student", "iat": now, "exp": now + 3600},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALG,
        )
        return sid, {"Authorization": f"Bearer {tok}"}

    yield _make

    for sid in created:
        docker(
            "exec",
            PG_CONTAINER,
            "psql",
            "-U",
            "kodmod",
            "-d",
            "kodmod_test",
            "-c",
            f"DELETE FROM students WHERE id = '{sid}'",
            check=False,
        )
