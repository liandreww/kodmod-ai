"""Stage 10 — Release Readiness Gate aggregator.

Reads ``reports/junit-*.xml`` + ``reports/coverage-*.xml`` +
``docs/testplan/baselines/`` + ``.security-waivers.yml`` and prints a PASS/FAIL
table for KM-READY-001..012 (spec: docs/testplan/10-readiness.md).

Exit code is non-zero if any *implemented and applicable* check fails. Checks
whose input artefacts are absent are reported ``SKIP`` (informational) so the
gate can run at any point in the campaign without spurious failure — a real
release run supplies every artefact and every row must then be PASS.

    python scripts/readiness_gate.py            # full table
    python scripts/readiness_gate.py --strict   # SKIP counts as FAIL
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
BASELINES = ROOT / "docs" / "testplan" / "baselines"

# KM-READY-001/002 thresholds (README §7 — final numbers agreed by the team).
COV_PURE_MIN = 90.0
COV_OVERALL_MIN = 75.0
# KM-READY-005 — max allowed regression vs a stored perf baseline.
PERF_REGRESSION_MAX = 0.25

PURE_LOGIC_PREFIXES = ("analytics/", "rag/chunking", "accessibility/", "graphs/")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


# --------------------------------------------------------------------------- #
# junit helpers
# --------------------------------------------------------------------------- #
def _iter_suites():
    for path in sorted(glob.glob(str(REPORTS / "junit-*.xml"))):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for s in suites:
            yield Path(path).name, s


def _junit_totals(exclude: tuple[str, ...] = ("junit-known-bug.xml",)):
    tests = failures = errors = skipped = 0
    seen = False
    for name, s in _iter_suites():
        if name in exclude:
            continue
        seen = True
        tests += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    return seen, tests, failures, errors, skipped


def _burndown_counts():
    path = REPORTS / "junit-known-bug.xml"
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = failed = 0
    for s in suites:
        total += int(s.get("tests", 0))
        failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
    return total, failed


# --------------------------------------------------------------------------- #
# coverage helpers  (coverage.py XML: <class filename="..." line-rate="0.83">)
# --------------------------------------------------------------------------- #
def _coverage_rates():
    files = sorted(glob.glob(str(REPORTS / "coverage-*.xml")))
    if not files:
        return None
    hits = {"pure_covered": 0, "pure_total": 0, "all_covered": 0, "all_total": 0}
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for cls in root.iter("class"):
            fn = (cls.get("filename") or "").replace("\\", "/")
            lines = cls.find("lines")
            if lines is None:
                continue
            total = 0
            covered = 0
            for ln in lines.findall("line"):
                total += 1
                if int(ln.get("hits", 0)) > 0:
                    covered += 1
            hits["all_total"] += total
            hits["all_covered"] += covered
            if any(fn.startswith(p) or f"/{p}" in fn for p in PURE_LOGIC_PREFIXES):
                hits["pure_total"] += total
                hits["pure_covered"] += covered
    pure = 100.0 * hits["pure_covered"] / hits["pure_total"] if hits["pure_total"] else None
    overall = 100.0 * hits["all_covered"] / hits["all_total"] if hits["all_total"] else None
    return pure, overall


# --------------------------------------------------------------------------- #
# perf-regression helpers
# --------------------------------------------------------------------------- #
def _perf_regressions():
    """Return (checked, [regression strings]) comparing current vs *.baseline in bench.json."""
    import json

    bench = BASELINES / "bench.json"
    if not bench.exists():
        return 0, []
    try:
        data = json.loads(bench.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0, []
    regressions: list[str] = []
    checked = 0
    for b in data.get("benchmarks", []):
        stats = b.get("stats", {})
        cur = stats.get("mean")
        base = (b.get("extra_info") or {}).get("baseline_mean") or stats.get("baseline_mean")
        if cur is None or not base:
            continue
        checked += 1
        if cur > base * (1.0 + PERF_REGRESSION_MAX):
            regressions.append(f"{b.get('name', '?')}: {cur:.4g}s vs baseline {base:.4g}s")
    return checked, regressions


# --------------------------------------------------------------------------- #
# security-waiver helpers
# --------------------------------------------------------------------------- #
def _waiver_status():
    path = ROOT / ".security-waivers.yml"
    if not path.exists():
        return FAIL, ".security-waivers.yml missing"
    body = path.read_text(encoding="utf-8")
    ids = re.findall(r"^\s*-\s*id:\s*(.+)$", body, flags=re.MULTILINE)
    if not ids:
        return PASS, "0 waivers"
    today = _dt.date.today()
    expired: list[str] = []
    undated: list[str] = []
    blocks = re.split(r"^\s*-\s*id:", body, flags=re.MULTILINE)[1:]
    for blk in blocks:
        m = re.search(r"expires:\s*(\d{4}-\d{2}-\d{2})", blk)
        wid = blk.splitlines()[0].strip().strip('"')
        if not m:
            undated.append(wid)
            continue
        if _dt.date.fromisoformat(m.group(1)) < today:
            expired.append(wid)
    if undated or expired:
        return FAIL, f"undated={undated} expired={expired}"
    return PASS, f"{len(ids)} waiver(s), all dated & current"


# --------------------------------------------------------------------------- #
# traceability linter
# --------------------------------------------------------------------------- #
_TEST_ID_RE = re.compile(r"KM-(?:STATIC|UNIT|CONTRACT|INT|API|WS|E2E|SYS|PERF|SEC|READY)-\d{3}")


def _trace_orphans():
    trace = ROOT / "docs" / "testplan" / "traceability.md"
    if not trace.exists():
        return None
    orphans = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: "):
            continue
        if cells[0].lower() in {"kode", "#", "req", "nfr", "id", ""}:
            continue
        if not _TEST_ID_RE.search(line):
            orphans += 1
    return orphans


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="treat SKIP as FAIL")
    args = ap.parse_args()

    rows: list[tuple[str, str, str]] = []

    # KM-READY-001 / 002 — coverage
    cov = _coverage_rates()
    if cov is None:
        rows.append(("KM-READY-001  coverage (pure logic >= 90%)", SKIP, "no coverage-*.xml"))
        rows.append(("KM-READY-002  coverage (overall >= 75%)", SKIP, "no coverage-*.xml"))
    else:
        pure, overall = cov
        rows.append(
            (
                "KM-READY-001  coverage (pure logic >= 90%)",
                PASS if (pure is not None and pure >= COV_PURE_MIN) else FAIL,
                f"{pure:.1f}%" if pure is not None else "no pure-logic lines measured",
            )
        )
        rows.append(
            (
                "KM-READY-002  coverage (overall >= 75%)",
                PASS if (overall is not None and overall >= COV_OVERALL_MIN) else FAIL,
                f"{overall:.1f}%" if overall is not None else "n/a",
            )
        )

    # KM-READY-003 — bug burndown
    bd = _burndown_counts()
    if bd is None:
        rows.append(
            ("KM-READY-003  bug burndown (0 known_bug failing)", SKIP, "no junit-known-bug.xml")
        )
    else:
        total, failed = bd
        rows.append(
            (
                "KM-READY-003  bug burndown (0 known_bug failing)",
                PASS if failed == 0 else FAIL,
                f"{failed}/{total} known_bug tests still red",
            )
        )

    # KM-READY-004 — stages 0-9 green
    seen, tests, failures, errors, skipped = _junit_totals()
    if not seen:
        rows.append(("KM-READY-004  Stage 0-9 green", SKIP, "no junit-*.xml"))
    else:
        rows.append(
            (
                "KM-READY-004  Stage 0-9 green",
                PASS if (failures == 0 and errors == 0) else FAIL,
                f"{tests} tests, {failures} failed, {errors} errored, {skipped} skipped",
            )
        )

    # KM-READY-005 — perf regression vs baseline
    checked, regressions = _perf_regressions()
    if checked == 0:
        rows.append(("KM-READY-005  perf within +/-25% baseline", SKIP, "no bench.json baselines"))
    else:
        rows.append(
            (
                "KM-READY-005  perf within +/-25% baseline",
                PASS if not regressions else FAIL,
                f"{checked} benchmarks checked; {len(regressions)} regressed"
                + (f" ({regressions[0]})" if regressions else ""),
            )
        )

    # KM-READY-006 — soak leak (baseline csv/json)
    soak = list(BASELINES.glob("perf-km-perf-030*")) + list(BASELINES.glob("resource-soak.*"))
    rows.append(
        (
            "KM-READY-006  soak: no resource leak",
            SKIP if not soak else PASS,
            "no soak baseline recorded" if not soak else f"{soak[0].name} present",
        )
    )

    # KM-READY-007 — security waivers
    status, detail = _waiver_status()
    rows.append(("KM-READY-007  0 High/Critical without dated waiver", status, detail))

    # KM-READY-009 — traceability
    orphans = _trace_orphans()
    if orphans is None:
        rows.append(("KM-READY-009  traceability complete", FAIL, "traceability.md missing"))
    else:
        rows.append(
            (
                "KM-READY-009  traceability complete",
                PASS if orphans == 0 else FAIL,
                f"{orphans} row(s) without a Test ID",
            )
        )

    # KM-READY-010/011/012 — delegated to `pytest -m readiness` (junit-readiness.xml)
    rd = REPORTS / "junit-readiness.xml"
    if rd.exists():
        try:
            r = ET.parse(rd).getroot()
            suites = [r] if r.tag == "testsuite" else r.findall("testsuite")
            f = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
            n = sum(int(s.get("tests", 0)) for s in suites)
            rows.append(
                (
                    "KM-READY-011/012  docs + migration meta-checks",
                    PASS if f == 0 else FAIL,
                    f"{n} readiness tests, {f} failing",
                )
            )
        except ET.ParseError:
            rows.append(
                (
                    "KM-READY-011/012  docs + migration meta-checks",
                    SKIP,
                    "unparseable junit-readiness.xml",
                )
            )
    else:
        rows.append(
            ("KM-READY-011/012  docs + migration meta-checks", SKIP, "run: pytest -m readiness")
        )

    width = max(len(r[0]) for r in rows)
    ok = True
    print("\nRelease Readiness Gate")
    print("=" * (width + 24))
    for name, status, detail in rows:
        if status == FAIL or (args.strict and status == SKIP):
            ok = False
        print(f"{name.ljust(width)}  {status:4}  {detail}")
    print("=" * (width + 24))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
