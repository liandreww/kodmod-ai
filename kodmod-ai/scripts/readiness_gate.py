"""Stage 10 — Release Readiness Gate aggregator.

Reads reports/junit-*.xml + coverage-*.xml + docs/testplan/baselines/ and prints
a PASS/FAIL table for KM-READY-001..012. See docs/testplan/10-readiness.md.

Scaffold: the checks below are wired to real artefacts where they already exist
and marked TODO where a later session must finish them. Exit code is non-zero if
any implemented check fails.
"""

from __future__ import annotations

import glob
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def _junit_totals() -> tuple[int, int, int, int]:
    tests = failures = errors = skipped = 0
    for path in glob.glob(str(REPORTS / "junit-*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for s in suites:
            tests += int(s.get("tests", 0))
            failures += int(s.get("failures", 0))
            errors += int(s.get("errors", 0))
            skipped += int(s.get("skipped", 0))
    return tests, failures, errors, skipped


def _xpass_count() -> int:
    """Unexpected passes = xfail(strict) that started passing → promote to assert."""
    n = 0
    for path in glob.glob(str(REPORTS / "junit-*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            for child in case:
                if child.tag == "failure" and "XPASS" in (child.get("message") or ""):
                    n += 1
    return n


def main() -> int:
    rows: list[tuple[str, bool, str]] = []

    tests, failures, errors, skipped = _junit_totals()
    rows.append(
        (
            "KM-READY-004  Stage 0-9 green",
            failures == 0 and errors == 0,
            f"{tests} tests, {failures} failed, {errors} errored, {skipped} skipped",
        )
    )

    xpass = _xpass_count()
    rows.append(
        (
            "KM-READY-003  bug burndown (0 unexpected XPASS)",
            xpass == 0,
            f"{xpass} xfail(strict) now passing — promote to plain asserts",
        )
    )

    trace = (ROOT / "docs/testplan/traceability.md").read_text(encoding="utf-8")
    rows.append(("KM-READY-009  traceability populated", "KM-" in trace, "traceability.md present"))

    # TODO(later session): KM-READY-001/002 coverage thresholds from coverage-*.xml,
    # KM-READY-005/006 perf deltas vs baselines/, KM-READY-007 security waivers,
    # KM-READY-010 randomized reruns, KM-READY-011/012 doc + migration checklist.

    width = max(len(r[0]) for r in rows)
    ok = True
    print("\nRelease Readiness Gate\n" + "=" * (width + 20))
    for name, passed, detail in rows:
        ok &= passed
        print(f"{name.ljust(width)}  {'PASS' if passed else 'FAIL'}  {detail}")
    print("=" * (width + 20))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
