"""Stage 8 (Performance / Load) fixtures.

Spec: docs/testplan/08-performance.md.

The micro-benchmarks (``benchmarks/``) call pure Python in-process and need no
service. The HTTP / WS scenarios talk to the host ``api`` process over real
``http://localhost:8000`` — the same model as Stage 4-7 — so their fixtures
commit to the shared Postgres and clean up on teardown.

**This stage is non-blocking** (see the spec): its job is to *record baselines*
into ``docs/testplan/baselines/`` and assert only generous ceilings so a genuine
regression (>25 % vs baseline, enforced at Stage 10 / KM-READY-005) is what
fails a release — not normal CI noise. The stub LLM answers in ~0 ms, so every
number here measures framework / graph / DB / checkpointer / serialisation
overhead, never model latency.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "docs" / "testplan" / "baselines"

# Keep the stage fast enough for a nightly job: every knob is overridable so a
# real load run can dial the numbers up without touching code.
SOAK_SECONDS = int(os.environ.get("KODMOD_PERF_SOAK_SECONDS", "20"))
HTTP_CONCURRENCY = int(os.environ.get("KODMOD_PERF_CONCURRENCY", "20"))
HTTP_ROUNDS = int(os.environ.get("KODMOD_PERF_ROUNDS", "3"))
WS_CONNECTIONS = int(os.environ.get("KODMOD_PERF_WS_CONNECTIONS", "20"))

pytestmark = [pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.environ.get("KODMOD_API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def _api_up(api_base_url: str) -> None:
    """Skip only the tests that actually need the live api (not the micro-benches)."""
    try:
        httpx.get(f"{api_base_url}/live", timeout=5.0).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"api not reachable at {api_base_url}: {exc}")


@pytest.fixture
async def client(api_base_url: str, _api_up: None):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(base_url=api_base_url, timeout=30.0) as c:
        yield c


def _token(sub, role: str = "student", *, ttl_s: int = 3600) -> str:
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
        "interaction_logs",
        "learning_sessions",
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
                full_name=over.pop("full_name", "Siswa Perf"),
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
                        "CAST(:sid AS uuid), CAST(:cid AS uuid), :m, 0.6, 5, :ls)"
                    ),
                    {"sid": str(student_id), "cid": str(cid), "m": m, "ls": datetime.now(UTC)},
                )

    return _seed


@pytest.fixture
async def concept_ids():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()
    async with async_session() as s:
        rows = (await s.execute(text("SELECT slug, id FROM concepts"))).all()
    return {slug: str(cid) for slug, cid in rows}


@pytest.fixture(scope="session")
def record_baseline():  # type: ignore[no-untyped-def]
    """Append a metric block to ``docs/testplan/baselines/perf-<name>.json``.

    Non-blocking: the file is advisory input to KM-READY-005. We merge rather
    than overwrite so a single run can record several scenarios.
    """
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    def _record(name: str, metrics: dict) -> None:
        path = BASELINE_DIR / f"perf-{name}.json"
        payload = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        payload.update(metrics)
        payload["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    return _record
