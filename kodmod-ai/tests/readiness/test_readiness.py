"""Stage 10 — Release Readiness Gate meta-checks.

Spec: docs/testplan/10-readiness.md. Stage 10 is not new *behaviour* testing —
it aggregates evidence from Stages 0-9 and enforces policy thresholds. The
numeric criteria (coverage KM-READY-001/002, perf deltas KM-READY-005/006,
security waivers KM-READY-007) are computed by ``scripts/readiness_gate.py``
from ``reports/`` + ``docs/testplan/baselines/``.

What lives here as pytest are the checks that are pure repo inspection and want
the ``--strict-markers`` / collection machinery: traceability completeness
(KM-READY-009), doc-sync checklist (KM-READY-011), migration policy
(KM-READY-012), and marker hygiene.

These run without any service (marker ``readiness``); the stage runner and
``make test-ready`` invoke ``pytest -m readiness`` alongside the gate script.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.readiness]

_REPO = Path(__file__).resolve().parents[2]
_TESTPLAN = _REPO / "docs" / "testplan"
_TRACE = _TESTPLAN / "traceability.md"

_TEST_ID_RE = re.compile(r"KM-(?:STATIC|UNIT|CONTRACT|INT|API|WS|E2E|SYS|PERF|SEC|READY)-\d{3}")


def _trace_text() -> str:
    return _TRACE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# KM-READY-009 — every traceability row carries >= 1 Test ID
# --------------------------------------------------------------------------- #
def test_km_ready_009_every_trace_row_has_a_test_id() -> None:
    orphan: list[str] = []
    for raw in _trace_text().splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        first = cells[0].lower()
        # skip header + separator rows
        if not first or set(cells[0]) <= set("-: ") or first in {"kode", "#", "req", "nfr", "id"}:
            continue
        if not _TEST_ID_RE.search(line):
            orphan.append(line[:120])
    assert not orphan, "traceability rows without a Test ID:\n" + "\n".join(orphan)


# --------------------------------------------------------------------------- #
# KM-READY-009b — every layered bug / finding code is mapped
# --------------------------------------------------------------------------- #
def test_km_ready_009b_all_bug_codes_mapped() -> None:
    text = _trace_text()
    missing: list[str] = []
    for n in range(1, 24):  # #1..#23 explored findings
        row = re.search(rf"^\|\s*#{n}\s*\|.*$", text, flags=re.MULTILINE)
        if row and not _TEST_ID_RE.search(row.group(0)):
            missing.append(f"#{n}")
    for n in range(1, 17):  # L-1..L-16
        row = re.search(rf"^\|\s*L-{n}\b.*$", text, flags=re.MULTILINE)
        if row and not _TEST_ID_RE.search(row.group(0)):
            missing.append(f"L-{n}")
    assert not missing, f"bug/finding codes with no Test ID: {missing}"


# --------------------------------------------------------------------------- #
# KM-READY-004 — every stage catalog has its per-stage bodies (no placeholders)
# --------------------------------------------------------------------------- #
def test_km_ready_004_no_stage_placeholder_tests_remain() -> None:
    leftover = sorted(
        p.relative_to(_REPO).as_posix()
        for p in (_REPO / "tests").rglob("test_placeholder_stage*.py")
    )
    assert not leftover, f"placeholder stage tests still present: {leftover}"


def test_km_ready_004b_all_stage_dirs_have_real_tests() -> None:
    stage_dirs = {
        "static",
        "unit",
        "contract",
        "integration",
        "api",
        "ws",
        "e2e",
        "system",
        "performance",
        "security",
        "readiness",
    }
    empty: list[str] = []
    for d in stage_dirs:
        path = _REPO / "tests" / d
        if not path.exists():
            empty.append(f"{d} (missing)")
            continue
        real = [p for p in path.rglob("test_*.py") if "placeholder" not in p.name]
        if not real:
            empty.append(d)
    assert not empty, f"stage dirs with no real test files: {empty}"


# --------------------------------------------------------------------------- #
# KM-READY-007 — the security-waiver file exists and is well-formed
# --------------------------------------------------------------------------- #
def test_km_ready_007_security_waivers_file_wellformed() -> None:
    waivers = _REPO / ".security-waivers.yml"
    assert waivers.exists(), ".security-waivers.yml missing (KM-READY-007 needs it, even if empty)"
    body = waivers.read_text(encoding="utf-8")
    # Every waiver entry must carry a dated 'expires:' — no open-ended waivers.
    entries = re.findall(r"^\s*-\s*id:", body, flags=re.MULTILINE)
    expires = re.findall(r"^\s*expires:\s*\d{4}-\d{2}-\d{2}", body, flags=re.MULTILINE)
    assert len(entries) == len(expires), (
        f"{len(entries)} waiver(s) but {len(expires)} dated 'expires:' — every waiver needs one"
    )


# --------------------------------------------------------------------------- #
# KM-READY-011 — docs updated for the health path / quiz status / qdrant / auth
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "KM-READY-011 — docs/API.md, docs/ARCHITECTURE.md, CLAUDE.md must reflect the real health "
    "path (/live not /health/live), quiz status, qdrant backend and the auth'd endpoint list "
    "before release"
)
def test_km_ready_011_docs_synced_for_health_path() -> None:
    hits = []
    for rel in ("docs/API.md", "ARCHITECTURE.md", "docs/ARCHITECTURE.md", "CLAUDE.md"):
        p = _REPO / rel
        if not p.exists():
            p = _REPO.parent / rel  # some docs live at the git root
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "/health/live" in text:
            hits.append(f"{rel}: still documents /health/live")
    assert not hits, "; ".join(hits)


# --------------------------------------------------------------------------- #
# KM-READY-012 — a migration path exists (alembic versions OR a documented decision)
# --------------------------------------------------------------------------- #
def test_km_ready_012_migration_path_declared() -> None:
    versions = (
        list((_REPO / "database" / "migrations" / "versions").glob("*.py"))
        if (_REPO / "database" / "migrations" / "versions").exists()
        else []
    )
    if versions:
        return  # real alembic history present

    # Otherwise the "schema from ORM create_all" decision must be written down.
    haystacks = [
        _REPO / "docs" / "testplan" / "03-integration.md",
        _REPO / "docs" / "testplan" / "README.md",
        _REPO / "CLAUDE.md",
    ]
    documented = any(
        p.exists()
        and re.search(
            r"create_all|schema dari ORM|schema from (the )?ORM", p.read_text(encoding="utf-8")
        )
        for p in haystacks
    )
    assert documented, (
        "no alembic versions/ and no documented 'schema from ORM create_all' decision "
        "(KM-READY-012)"
    )


# --------------------------------------------------------------------------- #
# marker hygiene — the stage runners select on these; keep them registered
# --------------------------------------------------------------------------- #
def test_km_ready_marker_registry_complete() -> None:
    pyproject = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    for marker in (
        "static",
        "unit",
        "contract",
        "integration",
        "api",
        "ws",
        "e2e",
        "system",
        "perf",
        "security",
        "readiness",
        "known_bug",
        "real_llm",
        "slow",
    ):
        assert re.search(rf'"\s*{marker}\s*:', pyproject), f"marker {marker!r} not registered"
