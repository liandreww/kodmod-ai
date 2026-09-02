"""KM-STATIC-040 / 041 / 042 / 044 / 045 / 060 — compose & image build gates.

Docker-dependent cases skip when no docker daemon is reachable. Image builds
carry ``@pytest.mark.slow`` so ``-m "static and not slow"`` (the default in the
runners) skips them while CI runs the full ``-m static``.

The two image builds also carry a *freshness guard*: if a matching image tag
already exists and is newer than its build inputs (Dockerfile + dep manifests /
stub sources) the build is skipped instead of re-run, so a local
``docker compose ... up -d --build`` is not duplicated. ``STATIC_FORCE_BUILD=1``
forces the build; CI runners start image-less so they always build.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

from tests.static._util import PROJECT_ROOT, has_mod, out, requires_docker, resolve, run

pytestmark = pytest.mark.static

COMPOSE = ["docker", "compose", "-p", "kodmod-test", "-f", "docker/docker-compose.test.yml"]

FORCE_BUILD = os.getenv("STATIC_FORCE_BUILD") == "1"


def _image_created(ref: str) -> float | None:
    """Epoch seconds of an image's creation, or ``None`` if it doesn't exist."""
    proc = run(["docker", "image", "inspect", "-f", "{{.Created}}", ref], timeout=30)
    if proc.returncode != 0:
        return None
    try:
        return datetime.fromisoformat(proc.stdout.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _newest_mtime(*paths: Path) -> float:
    latest = 0.0
    for base in paths:
        if base.is_file():
            latest = max(latest, base.stat().st_mtime)
        elif base.is_dir():
            for f in base.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    latest = max(latest, f.stat().st_mtime)
    return latest


def _skip_if_fresh(tags: list[str], sources: list[Path]) -> None:
    if FORCE_BUILD:
        return
    newest_src = _newest_mtime(*sources)
    for tag in tags:
        created = _image_created(tag)
        if created is not None and created >= newest_src:
            pytest.skip(
                f"image {tag!r} already built and newer than its inputs "
                f"({', '.join(p.name for p in sources)}); set STATIC_FORCE_BUILD=1 to rebuild"
            )


@requires_docker
def test_compose_test_config_valid() -> None:  # KM-STATIC-040
    proc = run([*COMPOSE, "config", "-q"])
    assert proc.returncode == 0, out(proc)


@requires_docker
@pytest.mark.parametrize("profile", ["load", "qdrant"])
def test_compose_test_config_profiles(profile: str) -> None:  # KM-STATIC-041
    proc = run([*COMPOSE, "--profile", profile, "config", "-q"])
    assert proc.returncode == 0, out(proc)


@requires_docker
@pytest.mark.slow
def test_build_backend_image() -> None:  # KM-STATIC-042
    dockerfile = (PROJECT_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    # Dockerfile contract checks run regardless of whether we (re)build.
    assert "EXPOSE 8000" in dockerfile
    assert "USER ${APP_USER}" in dockerfile  # non-root runtime user

    # Only inputs the image actually consumes: the Dockerfile installs from
    # requirements.txt (not pyproject) and COPYs the source tree.
    _skip_if_fresh(
        ["kodmod-api:test"],
        [PROJECT_ROOT / "docker" / "Dockerfile", PROJECT_ROOT / "requirements.txt"],
    )
    proc = run(
        ["docker", "build", "-f", "docker/Dockerfile", "-t", "kodmod-api:test", "."],
        timeout=1800,
    )
    assert proc.returncode == 0, out(proc)


@requires_docker
@pytest.mark.slow
def test_build_llm_stub_image() -> None:  # KM-STATIC-044
    # Reuse the tag docker compose already produces (project `kodmod-test`,
    # service `llm-stub`) so a rebuild here overwrites it instead of adding a
    # second near-identical image.
    tag = "kodmod-test-llm-stub:latest"
    _skip_if_fresh([tag, "kodmod-llmstub:test"], [PROJECT_ROOT / "docker" / "llm_stub"])
    proc = run(
        ["docker", "build", "-f", "docker/llm_stub/Dockerfile", "-t", tag, "docker/llm_stub"],
        timeout=900,
    )
    assert proc.returncode == 0, out(proc)


def test_host_tooling_present() -> None:  # KM-STATIC-045
    assert has_mod("pytest")
    proc = run([sys.executable, "-m", "pytest", "--version"])
    assert proc.returncode == 0, out(proc)
    assert resolve("ruff", "ruff") is not None, "ruff not on host"
    assert resolve("mypy", "mypy") is not None, "mypy not on host"


@pytest.mark.skipif(resolve("alembic", "alembic") is None, reason="alembic not installed")
@pytest.mark.known_bug(
    "database/migrations/versions/ is empty — test bootstrap uses scripts.create_test_db"
)
def test_alembic_consistent() -> None:  # KM-STATIC-060
    proc = run([*resolve("alembic", "alembic"), "check"])  # type: ignore[misc]
    assert proc.returncode == 0, out(proc)
