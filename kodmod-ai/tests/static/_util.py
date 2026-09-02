"""Shared helpers for Stage 0 (Static & Build). Spec: docs/testplan/00-static.md

Stage 0 mostly shells out to external tools (ruff, mypy, bandit, pip-audit,
detect-secrets, docker) and runs child Python processes with a controlled
environment so the cached ``config.settings`` singleton is not polluted by the
pytest session env forced in ``tests/conftest.py``.

Every check degrades to ``pytest.skip`` when its tool is not installed, so the
suite stays green on a bare dev box and only runs the full gate in CI / a
``pip install -e ".[test]"`` environment.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# tests/static/_util.py -> kodmod-ai/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:  # 3.11+ stdlib; tomli fallback for older interpreters
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover
        _toml = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# subprocess plumbing
# --------------------------------------------------------------------------- #
def run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    """Thin ``subprocess.run`` wrapper: captured text output, no ``check``."""
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def minimal_env(**extra: str) -> dict[str, str]:
    """A clean environment for a child ``python -c`` process: just enough for the
    interpreter to start, plus ``PYTHONPATH`` at the project root. Deliberately
    omits ENV / DB_* / ANTHROPIC_API_KEY so ``config.settings`` sees its
    defaults."""
    keep = (
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "PATHEXT",
        "COMSPEC",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONHASHSEED",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
    )
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def out(proc: subprocess.CompletedProcess[str]) -> str:
    """stdout+stderr, tail-trimmed, for assertion messages."""
    blob = (proc.stdout or "") + (proc.stderr or "")
    return blob[-4000:]


# --------------------------------------------------------------------------- #
# tool discovery
# --------------------------------------------------------------------------- #
def load_pyproject() -> dict:
    """Parsed ``pyproject.toml`` or skip if no TOML parser is available."""
    if _toml is None:  # pragma: no cover
        pytest.skip("no tomllib/tomli to parse pyproject.toml")
    return _toml.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def has_mod(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def has_cli(name: str) -> bool:
    return shutil.which(name) is not None


def resolve(mod: str, cli: str) -> list[str] | None:
    """Prefer ``python -m <mod>`` (same interpreter as pytest), fall back to a
    CLI on PATH, else ``None`` (caller skips)."""
    if has_mod(mod):
        return [sys.executable, "-m", mod]
    if has_cli(cli):
        return [cli]
    return None


def requires(mod: str, cli: str | None = None):
    cli = cli or mod
    return pytest.mark.skipif(resolve(mod, cli) is None, reason=f"{cli} not installed")


def _docker_ready() -> bool:
    if not has_cli("docker"):
        return False
    try:
        return run(["docker", "info"], timeout=25).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


requires_docker = pytest.mark.skipif(not _docker_ready(), reason="docker daemon unavailable")
