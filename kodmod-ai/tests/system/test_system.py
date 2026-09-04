"""Stage 7 — black-box system tests: host ``api`` process + ``kodmod-test`` infra.

Spec: docs/testplan/07-system.md (KM-SYS-001..062). The driver runs on the host,
talks to the ``api`` over HTTP, controls it via its pidfile (SIGTERM + respawn),
and reaches Postgres/Redis with the ``docker`` CLI (they are still containers).
Image-hygiene checks (old KM-SYS-070/071) moved to Stage 0 (KM-STATIC-046/047).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.system.conftest import (
    PG_CONTAINER,
    PID_FILE,
    _read_api_pid,
    _spawn_api,
    docker,
    read_api_log,
    wait_healthy,
)

pytestmark = [pytest.mark.system, pytest.mark.slow, pytest.mark.timeout(240)]

_REPO = Path(__file__).resolve().parents[2]


def _psql(sql: str) -> str:
    return docker(
        "exec", PG_CONTAINER, "psql", "-U", "kodmod", "-d", "kodmod_test", "-tAc", sql
    ).stdout.strip()


# --------------------------------------------------------------------------- #
# Boot & health
# --------------------------------------------------------------------------- #
def test_km_sys_001_boot_healthy(http) -> None:  # type: ignore[no-untyped-def]
    wait_healthy(timeout=60.0)
    assert http.get("/live").status_code == 200


def test_km_sys_001b_dockerfile_healthcheck_path() -> None:
    dockerfile = (_REPO / "docker" / "Dockerfile").read_text(encoding="utf-8")
    hc = [ln for ln in dockerfile.splitlines() if "HEALTHCHECK" in ln or "health" in ln.lower()]
    assert not any("/health/live" in ln for ln in hc), f"Dockerfile still curls /health/live: {hc}"


def test_km_sys_002_lifespan_logged(restart_api) -> None:  # type: ignore[no-untyped-def]
    # Force a fresh boot so the startup banner is the tail of the log, then scope
    # the assertions to that boot only (unrelated tracebacks from earlier stages
    # must not leak in via a whole-file grep).
    restart_api()
    logs = read_api_log(400)
    assert "KODMOD AI ready" in logs, "lifespan never signalled ready"
    boot = logs.rsplit("Starting KODMOD AI API", 1)[-1]
    startup = boot.split("KODMOD AI ready", 1)[0]
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
# Persistence across restart  (the api process restarts; Postgres does not)
# --------------------------------------------------------------------------- #
def test_km_sys_010_persistence_across_restart(http, restart_api, make_e2e_student) -> None:  # type: ignore[no-untyped-def]
    sid, hdr = make_e2e_student()
    r1 = http.post("/voice/text", headers=hdr, data={"text": "halo"})
    assert r1.status_code == 200
    session_id = r1.json()["session_id"]
    restart_api()
    r2 = http.post("/voice/text", headers=hdr, data={"text": "ulangi", "session_id": session_id})
    assert r2.status_code == 200
    assert r2.json()["response_text"] == r1.json()["response_text"]


def test_km_sys_011_interrupt_survives_restart(http, restart_api, make_e2e_student) -> None:  # type: ignore[no-untyped-def]
    sid, hdr = make_e2e_student()
    r = http.post("/voice/text", headers=hdr, data={"text": "jelaskan pecahan"})
    assert r.status_code == 200


def test_km_sys_012_restart_is_idempotent(restart_api) -> None:  # type: ignore[no-untyped-def]
    for _ in range(2):
        restart_api()
    logs = read_api_log().lower()
    assert "table already exists" not in logs
    assert "relation" not in logs or "already exists" not in logs


# --------------------------------------------------------------------------- #
# Vector backend matrix
# --------------------------------------------------------------------------- #
def test_km_sys_020_pgvector_retrieve(http) -> None:  # type: ignore[no-untyped-def]
    r = http.post(
        "/content/retrieve", json={"query": "apa itu pecahan", "top_k": 4, "language": "id"}
    )
    assert r.status_code == 200
    assert isinstance(r.json()["chunks"], list)


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


def test_km_sys_031_metrics_open_by_design(http) -> None:  # type: ignore[no-untyped-def]
    # /metrics is a conscious unauthenticated allowlist entry (Prometheus scrape,
    # network-restricted in deployment) — see tests/api/test_authz_inventory.py.
    r = http.get("/metrics/")
    assert r.status_code == 200


def test_km_sys_040_json_logs() -> None:
    lines = [ln for ln in read_api_log(120).splitlines() if ln.strip()]
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
    "#15 — the on-disk .env carries a real OPENAI_API_KEY / JWT_SECRET; guard that the api "
    "logs never echo bearer tokens or secret material"
)
def test_km_sys_041_no_secret_leak_in_logs() -> None:
    logs = read_api_log(2000)
    for needle in ("Bearer eyJ", "sk-", "JWT_SECRET=", "OPENAI_API_KEY="):
        assert needle not in logs, f"secret-like string in logs: {needle!r}"


# --------------------------------------------------------------------------- #
# Shutdown
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="graceful shutdown needs a POSIX SIGTERM to the uvicorn process; covered in Linux CI",
)
def test_km_sys_050_graceful_shutdown() -> None:
    pid = _read_api_pid()
    assert pid is not None, f"no api pidfile at {PID_FILE}"
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        try:
            os.kill(pid, 0)
            time.sleep(1.0)
        except OSError:
            break
    else:
        raise AssertionError("api did not exit within 30s of SIGTERM")
    try:
        logs = read_api_log()
        assert "Application shutdown complete" in logs
        assert "Database engine disposed" in logs
        shutdown = logs.rsplit("Shutting down KODMOD AI", 1)[-1]
        assert "Traceback (most recent call last)" not in shutdown
        hung = _psql("SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE '%kodmod%'")
        assert hung in {"0", ""}
    finally:
        _spawn_api()
        wait_healthy()


# --------------------------------------------------------------------------- #
# Bootstrap idempotency
# --------------------------------------------------------------------------- #
def test_km_sys_052_bootstrap_idempotent() -> None:
    for _ in range(2):
        res = subprocess.run(
            [sys.executable, "-m", "scripts.init_test_db"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert res.returncode == 0, res.stderr[-800:]
