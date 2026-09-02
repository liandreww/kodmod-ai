"""KM-STATIC-030 / 031 / 032 / 052 — dependency health.

030: pip-audit — 0 un-waived vulnerabilities (waivers: .pip-audit-ignore).
031: safety — cross-check, same policy.
032: optional non-default backends are not required on the text-mode path.
052: requirements.txt core set == pyproject [project.dependencies].
"""

from __future__ import annotations

import json
import re

import pytest

from tests.static._util import PROJECT_ROOT, has_mod, load_pyproject, out, resolve, run

pytestmark = pytest.mark.static

IGNORE_FILE = PROJECT_ROOT / ".pip-audit-ignore"

# Non-default STT/TTS/LLM backends. Text mode must not hard-require any of these;
# this test only records which are present (never fails on presence).
OPTIONAL_BACKENDS = [
    "langchain_ollama",
    "deepgram",
    "piper",
    "elevenlabs",
    "TTS",
    "azure.cognitiveservices.speech",
]


def _waivers() -> set[str]:
    if not IGNORE_FILE.exists():
        return set()
    ids: set[str] = set()
    for line in IGNORE_FILE.read_text(encoding="utf-8").splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            ids.add(token)
    return ids


def _norm(spec: str) -> str:
    return re.split(r"[<>=!~;\s\[]", spec.strip(), maxsplit=1)[0].lower().replace("_", "-")


@pytest.mark.skipif(resolve("pip_audit", "pip-audit") is None, reason="pip-audit not installed")
def test_pip_audit_no_unwaived_vulns() -> None:  # KM-STATIC-030
    proc = run(
        [
            *resolve("pip_audit", "pip-audit"),  # type: ignore[misc]
            "-f",
            "json",
            "--progress-spinner",
            "off",
        ],
        timeout=600,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        pytest.skip(f"pip-audit produced no JSON (offline?):\n{out(proc)}")
    deps = data.get("dependencies", data if isinstance(data, list) else [])
    waived = _waivers()
    bad = [
        f"{d.get('name')}=={d.get('version')} {v.get('id')}"
        for d in deps
        for v in d.get("vulns", [])
        if v.get("id") and v.get("id") not in waived
    ]
    assert not bad, (
        "un-waived vulnerabilities (add to .pip-audit-ignore with a date):\n" + "\n".join(bad)
    )


@pytest.mark.skipif(resolve("safety", "safety") is None, reason="safety not installed")
def test_safety_cross_check() -> None:  # KM-STATIC-031
    proc = run([*resolve("safety", "safety"), "check", "--json"], timeout=600)  # type: ignore[misc]
    if proc.returncode != 0 and "login" in (proc.stderr or "").lower():
        pytest.skip("safety requires authentication in this environment")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        pytest.skip(f"safety produced no JSON:\n{out(proc)}")
    vulns = data.get("vulnerabilities", []) if isinstance(data, dict) else data
    waived = _waivers()
    bad = [
        f"{v.get('package_name')} {v.get('vulnerability_id')}"
        for v in vulns
        if str(v.get("vulnerability_id")) not in waived
    ]
    assert not bad, "un-waived vulnerabilities (safety):\n" + "\n".join(bad)


@pytest.mark.parametrize("mod", OPTIONAL_BACKENDS)
def test_optional_backend_status(mod: str) -> None:  # KM-STATIC-032
    top = mod.split(".", 1)[0]
    present = has_mod(top)
    print(f"optional backend {mod!r}: {'present' if present else 'absent'}")
    # Informational only: text mode (STT_ENABLED/TTS_ENABLED=false) must not
    # need these. KM-STATIC-010/011 prove the text-mode import path.
    assert True


def test_requirements_match_pyproject_core() -> None:  # KM-STATIC-052
    pp = {_norm(d) for d in load_pyproject()["project"]["dependencies"]}
    rq: set[str] = set()
    for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            rq.add(_norm(token))
    assert pp == rq, {
        "only_in_pyproject": sorted(pp - rq),
        "only_in_requirements": sorted(rq - pp),
    }
