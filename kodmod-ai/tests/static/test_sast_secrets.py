"""KM-STATIC-020 / 021 / 022 — SAST and secret hygiene.

020: bandit, 0 findings at severity HIGH.
021: detect-secrets against a committed baseline (skipped until the baseline
     exists — create with ``detect-secrets scan > .secrets.baseline``).
022: no raw provider keys / 64-hex JWT secrets in git-tracked files.
"""

from __future__ import annotations

import json
import re

import pytest

from tests.static._util import PROJECT_ROOT, has_mod, out, resolve, run

pytestmark = pytest.mark.static

BANDIT_TARGETS = (
    "agents graphs tools rag api analytics accessibility memory voice config database scripts"
).split()

BASELINE = PROJECT_ROOT / ".secrets.baseline"

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"""JWT_SECRET['"\s:=]{1,4}[0-9a-fA-F]{64}"""),
]
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".drawio",
    ".pyc",
    ".woff",
    ".woff2",
    ".ipynb",
}


@pytest.mark.skipif(resolve("bandit", "bandit") is None, reason="bandit not installed")
def test_bandit_no_high_severity() -> None:  # KM-STATIC-020
    cmd = [
        *resolve("bandit", "bandit"),
        "-q",
        "-r",
        *BANDIT_TARGETS,  # type: ignore[misc]
        "-x",
        "tests",
        "-f",
        "json",
    ]
    proc = run(cmd)  # bandit exits 1 when it reports issues; parse regardless
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        pytest.fail(f"bandit produced no JSON:\n{out(proc)}")
    highs = [r for r in data.get("results", []) if r.get("issue_severity") == "HIGH"]
    detail = "\n".join(
        f"  {r['filename']}:{r['line_number']} {r['test_id']} {r['issue_text']}" for r in highs
    )
    assert not highs, f"bandit HIGH findings:\n{detail}"


@pytest.mark.skipif(
    not has_mod("detect_secrets") or not BASELINE.exists(),
    reason="detect-secrets or .secrets.baseline missing",
)
def test_detect_secrets_against_baseline() -> None:  # KM-STATIC-021
    proc = run(
        [
            *resolve("detect_secrets", "detect-secrets"),  # type: ignore[misc]
            "scan",
            "--baseline",
            ".secrets.baseline",
        ]
    )
    assert proc.returncode == 0, out(proc)


def test_no_raw_secrets_in_tracked_files() -> None:  # KM-STATIC-022
    ls = run(["git", "ls-files"])
    assert ls.returncode == 0, out(ls)
    tracked = [line for line in ls.stdout.splitlines() if line]

    # .env is gitignored — it must never appear among tracked files.
    assert not [f for f in tracked if f.rsplit("/", 1)[-1] == ".env"], ".env is tracked!"

    offenders: list[str] = []
    for rel in tracked:
        path = PROJECT_ROOT / rel
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            m = pat.search(text)
            if m:
                offenders.append(f"{rel}: {m.group(0)[:16]}…")
    assert not offenders, "possible secrets in tracked files:\n" + "\n".join(offenders)
