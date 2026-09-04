"""Stage 7 (System / black-box) fixtures.

The driver runs natively on the host. Only the infra (Postgres, Redis, llm-stub)
runs in Docker via the ``kodmod-test`` compose project; the ``api`` under test is
a host ``uvicorn`` process started by ``scripts/serve_test_api`` (its PID is in
``reports/.api.pid``). These tests use whatever ``api`` is already serving
``http://localhost:8000`` — ``scripts/run_tests.{ps1,sh}`` start/stop it for
Stage 7. Postgres is still a container, so ``docker exec`` against it is fine.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

API = os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")
PG_CONTAINER = os.environ.get("KODMOD_PG_CONTAINER", "kodmod-postgres-test")
REPO_ROOT = Path(__file__).resolve().parents[2]
PID_FILE = REPO_ROOT / "reports" / ".api.pid"
API_LOG = REPO_ROOT / "reports" / "api.log"

pytestmark = [pytest.mark.system, pytest.mark.slow]


def read_api_log(tail: int = 400) -> str:
    """Last ``tail`` lines of the host api's log (``scripts/serve_test_api`` always
    writes it). Replaces ``docker logs kodmod-api-test`` from the old container model."""
    try:
        lines = API_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-tail:])


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


def _read_api_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _spawn_api() -> None:
    """Start a fresh host ``serve_test_api`` process (writes its own pidfile)."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # Handle deliberately left open: it must outlive this call for the child.
    log = open(REPO_ROOT / "reports" / "api.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "scripts.serve_test_api"],
        cwd=str(REPO_ROOT),
        stdout=log,
        stderr=log,
        creationflags=creationflags,
    )


@pytest.fixture(scope="session", autouse=True)
def compose_stack():  # type: ignore[no-untyped-def]
    try:
        httpx.get(f"{API}/live", timeout=3.0).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(
            f"api not reachable at {API} ({exc}) — start the infra + host api first: "
            "docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub "
            "&& python -m scripts.init_test_db && python -m scripts.serve_test_api"
        )
    yield


@pytest.fixture
def http() -> httpx.Client:
    with httpx.Client(base_url=API, timeout=30.0) as c:
        yield c


@pytest.fixture
def restart_api():  # type: ignore[no-untyped-def]
    """Restart the host ``api`` process (SIGTERM the pidfile PID, then respawn).

    Proves state survives an app restart — the Postgres container the checkpoint
    lives in is untouched.
    """

    def _restart() -> None:
        pid = _read_api_pid()
        if pid is None:
            pytest.skip(f"no api pidfile at {PID_FILE} — cannot drive a restart")
        sig = signal.SIGTERM
        if sys.platform == "win32":
            sig = getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM)
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, OSError):
            pass
        for _ in range(30):
            try:
                os.kill(pid, 0)
                time.sleep(1.0)
            except OSError:
                break
        _spawn_api()
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
            f"INSERT INTO students (id, full_name, accessibility_profile, preferred_language, "
            f"voice_settings, created_at, updated_at) "
            f"VALUES ('{sid}', 'Siswa SYS', 'blind', 'id', '{{}}', now(), now())",
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
