"""KM-STATIC-010 / KM-STATIC-011 — import smoke.

010: every top-level package imports in a clean child process.
011: every submodule under the application packages imports individually.

Known-dead modules (BUG-1, #7, #9) are marked ``known_bug`` — the case stays
RED until the dead import is removed, then it goes green on its own (no marker
to delete). ``KNOWN_DEAD`` is currently empty; add an entry only for a module
whose *top-level* import is broken by a tracked bug.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.static._util import PROJECT_ROOT, minimal_env, out, run

pytestmark = pytest.mark.static

# KM-STATIC-010 — the exact list used by scripts/run_tests.sh and CI.
TOP_LEVEL = [
    "agents",
    "graphs",
    "tools",
    "rag",
    "api",
    "analytics",
    "accessibility",
    "memory",
    "config",
    "database",
    "models",
]

# KM-STATIC-011 — walk *.py under these application roots (spec scope + tools/graphs).
WALK_ROOTS = [
    "agents",
    "api.routes",
    "api.websockets",
    "rag",
    "analytics",
    "accessibility",
    "memory",
    "tools",
    "graphs",
]

# module dotted-name -> finding ref. Tagged @pytest.mark.known_bug so the case
# is RED until the dead import is removed, then green on its own.
# (BUG-1 `agents.tutoring_agent`, #7 `api.routes.exercise`, #9 `tools.rag_tool`
#  all import cleanly now — #7/#9 still carry deeper bugs caught by mypy/contract.)
KNOWN_DEAD: dict[str, str] = {}


def test_top_level_packages_import() -> None:  # KM-STATIC-010
    code = "import " + ", ".join(TOP_LEVEL)
    proc = run([sys.executable, "-c", code], env=minimal_env(), cwd=PROJECT_ROOT)
    assert proc.returncode == 0, out(proc)


def _iter_submodules() -> list[str]:
    found: set[str] = set()
    for pkg in WALK_ROOTS:
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.submodule_search_locations:
            continue
        base = Path(next(iter(spec.submodule_search_locations)))
        found.add(pkg)
        for py in base.rglob("*.py"):
            parts = py.relative_to(base).with_suffix("").parts
            if "__pycache__" in parts or "migrations" in parts or "tests" in parts:
                continue
            tail = ".".join(p for p in parts if p != "__init__")
            found.add(f"{pkg}.{tail}" if tail else pkg)
    return sorted(found)


def _params() -> list:
    params = []
    for name in _iter_submodules():
        marks = []
        if name in KNOWN_DEAD:
            marks.append(pytest.mark.known_bug(KNOWN_DEAD[name]))
        params.append(pytest.param(name, marks=marks, id=name))
    return params


@pytest.mark.parametrize("modname", _params())
def test_submodule_imports(modname: str) -> None:  # KM-STATIC-011
    importlib.import_module(modname)
