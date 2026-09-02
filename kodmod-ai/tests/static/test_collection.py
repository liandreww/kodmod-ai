"""KM-STATIC-050 / 051 — pytest markers & collection are clean.

050: every custom marker used in tests/ is registered in pyproject.toml and
     ``--collect-only`` raises no PytestUnknownMarkWarning.
051: ``pytest --collect-only`` over all of tests/ reports 0 collection errors
     (guards against dead-import regressions like #18).
"""

from __future__ import annotations

import re
import sys

import pytest

from tests.static._util import load_pyproject, out, run

pytestmark = pytest.mark.static

_COLLECT = [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:randomly"]


def _declared_markers() -> set[str]:
    raw = load_pyproject()["tool"]["pytest"]["ini_options"]["markers"]
    return {entry.split(":", 1)[0].strip() for entry in raw}


def test_static_marker_registered() -> None:  # KM-STATIC-050 (a)
    assert "static" in _declared_markers(), "add 'static' to [tool.pytest.ini_options].markers"


def test_no_unknown_mark_warnings() -> None:  # KM-STATIC-050 (b)
    proc = run([*_COLLECT, "-W", "error::pytest.PytestUnknownMarkWarning"])
    assert proc.returncode == 0, out(proc)


def test_collection_has_no_errors() -> None:  # KM-STATIC-051
    proc = run(_COLLECT)
    assert proc.returncode == 0, out(proc)
    m = re.search(r"(\d+)\s+error", proc.stdout)
    assert not m or m.group(1) == "0", out(proc)
