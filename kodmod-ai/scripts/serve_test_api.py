"""
KODMOD AI — Run the API on the host for Stage 4-9 tests
======================================================

The test model runs only *infra* in Docker (`postgres`, `redis`, `llm-stub` via
`docker/docker-compose.test.yml`). The backend itself runs **natively on the
host** through this launcher instead of the `api` container, so a source change
is picked up by a plain restart — no `docker build`.

It locks the test environment into ``os.environ`` *before* anything imports
``config.settings`` — see ``scripts/_testenv.py`` for the values.

Run from ``kodmod-ai/`` once the infra + schema/seed are ready::

    docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub
    python -m scripts.init_test_db
    python -m scripts.serve_test_api            # serves http://localhost:8000

``scripts/run_tests.{ps1,sh}`` start/stop this automatically for Stage 4+.

Overrides (shell env): ``ENV=staging`` (KM-SYS-060), ``KODMOD_API_PORT=8001``, a
real provider for the ``@real_llm`` smoke. ``SERVE_TEST_API_RELOAD=1`` turns on
uvicorn reload.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from scripts._testenv import ROOT, apply_test_env

PID_FILE = ROOT / "reports" / ".api.pid"
API_LOG = ROOT / "reports" / "api.log"

# When reload is on, only watch source packages — never the repo root. Otherwise
# watchfiles picks up every append to reports/api.log and every baseline JSON the
# perf suite writes (docs/testplan/baselines/), plus OneDrive sync churn, and the
# app reloads mid-run — dropping in-flight HTTP/WS turns (KM-PERF-020 et al.).
RELOAD_DIRS = [
    "api",
    "agents",
    "graphs",
    "tools",
    "rag",
    "analytics",
    "accessibility",
    "memory",
    "config",
    "database",
    "prompts",
]
RELOAD_EXCLUDES = ["*.log", "*.json", "reports/*", "docs/*", ".runtime/*", "**/__pycache__/*"]


def _log_config() -> dict:
    """docker/log_conf.json (JSON stdout) + a file handler so Stage 7 log-scraping
    tests have a stable `reports/api.log` no matter how the server was started.
    Append mode: KM-SYS-012 needs pre- and post-restart lines in one file."""
    cfg = json.loads((ROOT / "docker" / "log_conf.json").read_text(encoding="utf-8"))
    cfg.setdefault("handlers", {})["file"] = {
        "class": "logging.FileHandler",
        "formatter": "json",
        "filename": str(API_LOG),
        "mode": "a",
        "encoding": "utf-8",
    }
    for name in ("root", *cfg.get("loggers", {})):
        node = cfg["root"] if name == "root" else cfg["loggers"][name]
        node.setdefault("handlers", [])
        if "file" not in node["handlers"]:
            node["handlers"].append("file")
    return cfg


def main() -> None:
    apply_test_env()

    # On Windows a redirected stdout/stderr defaults to cp1252, so any log line
    # with a non-latin-1 char (e.g. "→" in an agent log) raises UnicodeEncodeError
    # inside logging on *every* turn. Under concurrency the resulting stderr
    # traceback dumps serialise on the event loop and blow the latency budget
    # (KM-PERF-020). Force UTF-8 and never raise on an odd char.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")

    import uvicorn

    # LangGraph's AsyncPostgresSaver uses psycopg async, which refuses to run on
    # Windows' default ProactorEventLoop (uvicorn picks it for a single-process
    # server). Point uvicorn's loop factory at a SelectorEventLoop there so the
    # checkpointer — hence the whole lifespan — can start. Linux/CI keeps "auto".
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    host = os.environ.get("KODMOD_API_HOST", "0.0.0.0")  # noqa: S104 — local test server
    port = int(os.environ.get("KODMOD_API_PORT", "8000"))
    reload = os.environ.get("SERVE_TEST_API_RELOAD") == "1"

    run_kwargs: dict = {
        "host": host,
        "port": port,
        "workers": 1,
        "reload": reload,
        "loop": loop,
        "log_config": _log_config(),
    }
    if reload:
        logging.getLogger("scripts.serve_test_api").warning(
            "uvicorn --reload is ON (SERVE_TEST_API_RELOAD=1) — do NOT use this for "
            "perf/e2e runs; watchfiles churn thrashes the app under concurrency."
        )
        run_kwargs["reload_dirs"] = RELOAD_DIRS
        run_kwargs["reload_excludes"] = RELOAD_EXCLUDES

    try:
        uvicorn.run("api.main:app", **run_kwargs)
    finally:
        try:
            if PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
