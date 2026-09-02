"""KM-STATIC-001..004 — lint, format, type-check gates.

Spec: docs/testplan/00-static.md. Oracle: the ruff / mypy configuration in
pyproject.toml. These assert the *target* (exit 0). A case that is red because
of a tracked-but-unfixed bug carries ``@pytest.mark.known_bug("#…")`` and a
row in traceability.md — it stays RED until the bug is fixed, then goes green
(no marker to remove, no xfail/xpass dance).
"""

from __future__ import annotations

import pytest

from tests.static._util import out, requires, resolve, run

pytestmark = pytest.mark.static

CORE_PKGS = "agents graphs tools rag api analytics accessibility memory voice config".split()


@requires("ruff")
def test_ruff_check_clean() -> None:  # KM-STATIC-001
    proc = run([*resolve("ruff", "ruff"), "check", "."])  # type: ignore[misc]
    assert proc.returncode == 0, out(proc)


@requires("ruff")
def test_ruff_format_clean() -> None:  # KM-STATIC-002
    proc = run([*resolve("ruff", "ruff"), "format", "--check", "."])  # type: ignore[misc]
    assert proc.returncode == 0, out(proc)


@requires("mypy")
@pytest.mark.known_bug(
    "#1 student.profile, #2 .language, #4 stream_tts, #5 quiz fields, "
    "#6 _load_mastery await, #7 generate_questions_for_student — "
    "62 mypy errors in 22 files; see traceability.md KM-STATIC-003"
)
def test_mypy_core_clean() -> None:  # KM-STATIC-003
    proc = run([*resolve("mypy", "mypy"), "--ignore-missing-imports", *CORE_PKGS])  # type: ignore[misc]
    assert proc.returncode == 0, out(proc)


@requires("mypy")
@pytest.mark.known_bug("tests/ typing debt — tightened stage by stage (KM-STATIC-004)")
def test_mypy_tests_clean() -> None:  # KM-STATIC-004
    proc = run([*resolve("mypy", "mypy"), "tests"])  # type: ignore[misc]
    assert proc.returncode == 0, out(proc)
