"""Stage 7 — black-box system tests against the ``kodmod-test`` compose stack.

Spec: docs/testplan/07-system.md (KM-SYS-001..071). Driver runs on the host and
talks to the containers over HTTP + ``docker`` CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.system.conftest import API_CONTAINER, PG_CONTAINER, docker, wait_healthy

pytestmark = [pytest.mark.system, pytest.mark.slow, pytest.mark.timeout(240)]

_REPO = Path(__file__).resolve().parents[2]


def _psql(sql: str) -> str:
    return docker(
        "exec", PG_CONTAINER, "psql", "-U", "kodmod", "-d", "kodmod_test", "-tAc", sql
    ).stdout.strip()


# --------------------------------------------------------------------------- #
# Boot & health
# --------------------------------------------------------------------------- #
def test_km_sys_001_boot_healthy() -> None:
    health = json.loads(
        docker("inspect", "--format", "{{json .State.Health}}", API_CONTAINER).stdout
    )
    assert health["Status"] == "healthy"


@pytest.mark.known_bug(
    "#13 — docker/Dockerfile HEALTHCHECK curls /health/live (404); the real path is /live. "
    "It only works because docker-compose.test.yml overrides the healthcheck."
)
def test_km_sys_001b_dockerfile_healthcheck_path() -> None:
    dockerfile = (_REPO / "docker" / "Dockerfile").read_text(encoding="utf-8")
    hc = [ln for ln in dockerfile.splitlines() if "HEALTHCHECK" in ln or "health" in ln.lower()]
    assert not any("/health/live" in ln for ln in hc), f"Dockerfile still curls /health/live: {hc}"


def test_km_sys_002_lifespan_logged() -> None:
    proc = docker("logs", API_CONTAINER)
    logs = proc.stdout + proc.stderr
    assert "KODMOD AI ready" in logs, "lifespan never signalled ready"
    # startup itself must be clean — no traceback BEFORE the ready marker
    startup = logs.split("KODMOD AI ready", 1)[0]
    assert "Traceback (most recent call last)" not in startup
    assert "Database initialized" in startup
    assert "graph compiled" in startup


def test_km_sys_003_checkpoint_tables_exist() -> None:
    tables = _psql(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE 'checkpoint%'"
    ).splitlines()
    assert any(t.strip() == "checkpoints" for t in tables)
    assert any("checkpoint_writes" in t for t in tables)


def test_km_sys_004_ready_end_to_end(http) -> None:  # type: ignore[no-untyped-def]
    body = http.get("/ready").json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


# --------------------------------------------------------------------------- #
# Persistence across restart
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 — /voice/text 500s on student.profile before graph.ainvoke, so no checkpoint is "
    "written and cross-restart conversation continuity cannot be exercised end-to-end"
)
def test_km_sys_010_persistence_across_restart(http, restart_api, make_e2e_student) -> None:  # type: ignore[no-untyped-def]
    sid, hdr = make_e2e_student()
    r1 = http.post("/voice/text", headers=hdr, data={"text": "halo"})
    assert r1.status_code == 200
    session_id = r1.json()["session_id"]
    restart_api()
    r2 = http.post("/voice/text", headers=hdr, data={"text": "ulangi", "session_id": session_id})
    assert r2.status_code == 200
    assert r2.json()["response_text"] == r1.json()["response_text"]


@pytest.mark.known_bug(
    "#1 — same blocker as KM-SYS-010 for the interrupt/resume-after-restart path"
)
def test_km_sys_011_interrupt_survives_restart(http, restart_api, make_e2e_student) -> None:  # type: ignore[no-untyped-def]
    sid, hdr = make_e2e_student()
    r = http.post("/voice/text", headers=hdr, data={"text": "jelaskan pecahan"})
    assert r.status_code == 200


def test_km_sys_012_restart_is_idempotent(restart_api) -> None:  # type: ignore[no-untyped-def]
    for _ in range(2):
        restart_api()
    logs = (
        docker("logs", API_CONTAINER, "--tail", "200").stdout
        + docker("logs", API_CONTAINER, "--tail", "200").stderr
    )
    assert "already exists" not in logs.lower()
    assert "relation" not in logs.lower() or "already exists" not in logs.lower()


# --------------------------------------------------------------------------- #
# Vector backend matrix
# --------------------------------------------------------------------------- #
def test_km_sys_020_pgvector_retrieve(http) -> None:  # type: ignore[no-untyped-def]
    r = http.post(
        "/content/retrieve", json={"query": "apa itu pecahan", "top_k": 4, "language": "id"}
    )
    assert r.status_code == 200
    assert isinstance(r.json()["chunks"], list)


@pytest.mark.known_bug(
    "#9 — tools/rag_tool.py imports QdrantStore from rag.stores.qdrant_store (missing); the "
    "RAGTool path to qdrant is dead. rag.retriever module functions still work."
)
def test_km_sys_021_qdrant_backend() -> None:
    from rag.stores import qdrant_store

    assert hasattr(qdrant_store, "QdrantStore")


# --------------------------------------------------------------------------- #
# Operational endpoints
# --------------------------------------------------------------------------- #
def test_km_sys_030_metrics_prometheus(http) -> None:  # type: ignore[no-untyped-def]
    r = http.get("/metrics/")
    assert r.status_code == 200
    assert "version=0.0.4" in r.headers["content-type"]
    assert "# HELP" in r.text


@pytest.mark.known_bug("#14 — /metrics is served without authentication (control observation)")
def test_km_sys_031_metrics_requires_auth(http) -> None:  # type: ignore[no-untyped-def]
    r = http.get("/metrics/")
    assert r.status_code in {401, 403}


def test_km_sys_040_json_logs() -> None:
    lines = [
        ln for ln in docker("logs", API_CONTAINER, "--tail", "80").stdout.splitlines() if ln.strip()
    ]
    parsed = 0
    for ln in lines:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and {"level", "msg"} & set(obj):
            parsed += 1
    assert parsed >= 1, "no JSON-formatted log lines found"


@pytest.mark.known_bug(
    "#15 — the on-disk .env carries a real OPENAI_API_KEY / JWT_SECRET; guard that container "
    "logs never echo bearer tokens or secret material"
)
def test_km_sys_041_no_secret_leak_in_logs() -> None:
    logs = docker("logs", API_CONTAINER).stdout + docker("logs", API_CONTAINER).stderr
    for needle in ("Bearer eyJ", "sk-", "JWT_SECRET=", "OPENAI_API_KEY="):
        assert needle not in logs, f"secret-like string in logs: {needle!r}"


# --------------------------------------------------------------------------- #
# Shutdown / compose wiring
# --------------------------------------------------------------------------- #
def test_km_sys_050_graceful_shutdown(restart_api) -> None:  # type: ignore[no-untyped-def]
    docker("stop", "-t", "15", API_CONTAINER)
    exit_code = docker("inspect", "--format", "{{.State.ExitCode}}", API_CONTAINER).stdout.strip()
    try:
        assert exit_code in {"0", "143"}  # clean, or SIGTERM
    finally:
        docker("start", API_CONTAINER)
        wait_healthy()


def test_km_sys_052_db_init_idempotent() -> None:
    # re-running the schema bootstrap must not error (CREATE TABLE IF NOT EXISTS + idempotent seed)
    res = docker(
        "exec", API_CONTAINER, "python", "-m", "scripts.create_test_db", check=False, timeout=120
    )
    assert res.returncode == 0, res.stderr[-800:]


def test_km_sys_070_image_runs_as_non_root() -> None:
    who = docker("exec", API_CONTAINER, "id", "-un").stdout.strip()
    assert who and who != "root"


@pytest.mark.skipif(sys.platform == "win32", reason="image size baseline recorded in Linux CI")
def test_km_sys_071_image_size_reasonable() -> None:
    size = int(
        docker("image", "inspect", "--format", "{{.Size}}", "kodmod-test-api").stdout.strip()
    )
    assert size < 2_500_000_000
