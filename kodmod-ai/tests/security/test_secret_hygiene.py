"""Stage 9 §7 — runtime secret hygiene.

Spec: docs/testplan/09-security.md §7 (KM-SEC-070..072).
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

import jwt as pyjwt
import pytest

pytestmark = [pytest.mark.security, pytest.mark.asyncio(loop_scope="session")]

_REPO = Path(__file__).resolve().parents[2]
_API_LOG = _REPO / "reports" / "api.log"

_SECRET_NEEDLES = (
    "sk-ant-",
    "sk-proj-",
    "JWT_SECRET=",
    "OPENAI_API_KEY=",
    "ANTHROPIC_API_KEY=",
)


# --------------------------------------------------------------------------- #
# KM-SEC-070 — secrets never land in the api log
# --------------------------------------------------------------------------- #
async def test_km_sec_070_no_secret_in_logs(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    if not _API_LOG.exists():
        pytest.skip("no reports/api.log — api not started by the stage runner")

    # Generate some traffic that carries a bearer token, then scan the log.
    _st, tok = await student_factory()
    for _ in range(3):
        await client.get("/student/me", headers={"Authorization": f"Bearer {tok}"})
        await client.get("/student/me", headers={"Authorization": "Bearer eyJ.deadbeef.sig"})

    log = _API_LOG.read_text(encoding="utf-8", errors="replace")
    for needle in _SECRET_NEEDLES:
        assert needle not in log, f"secret-like string in api.log: {needle!r}"
    # No full bearer JWT echoed (header value logged verbatim).
    assert not re.search(r"Bearer eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", log), (
        "a full Bearer JWT was written to api.log"
    )
    from config.settings import settings

    if settings.JWT_SECRET and len(settings.JWT_SECRET) > 8:
        assert settings.JWT_SECRET not in log, "the raw JWT_SECRET value appears in api.log"


# --------------------------------------------------------------------------- #
# KM-SEC-071 — secrets never land in a response body
# --------------------------------------------------------------------------- #
async def test_km_sec_071_no_secret_in_responses(client) -> None:  # type: ignore[no-untyped-def]
    from config.settings import settings

    bodies = []
    for path in ("/version", "/ready", "/live"):
        bodies.append((await client.get(path)).text)
    # a forced error body too
    now = int(time.time())
    bad = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "role": "student", "iat": now, "exp": now + 60},
        "wrong-secret-value-00000000",
        algorithm="HS256",
    )
    bodies.append(
        (await client.get("/student/me", headers={"Authorization": f"Bearer {bad}"})).text
    )

    blob = "\n".join(bodies)
    for needle in ("sk-ant-", "sk-proj-", "sk-"):
        assert needle not in blob
    for secret in (settings.JWT_SECRET, settings.OPENAI_API_KEY, settings.ANTHROPIC_API_KEY):
        if secret and len(str(secret)) > 8:
            assert str(secret) not in blob, "a configured secret value was returned in a response"

    version = (await client.get("/version")).json()
    # /version exposes provider names, never keys.
    assert "llm_provider" in version
    assert not any("key" in k.lower() or "secret" in k.lower() for k in version)


# --------------------------------------------------------------------------- #
# KM-SEC-072 — .env is not baked into the built image / not on the run path
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#15 — the on-disk .env carries real OPENAI_API_KEY / JWT_SECRET; it must be .dockerignore'd "
    "out of the image and the on-disk file rotated"
)
def test_km_sec_072_env_not_in_image_context() -> None:
    dockerignore = _REPO / ".dockerignore"
    assert dockerignore.exists(), ".dockerignore missing"
    patterns = {
        ln.strip()
        for ln in dockerignore.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    assert ".env" in patterns or "*.env" in patterns or "**/.env" in patterns, (
        f".dockerignore does not exclude .env: {sorted(patterns)}"
    )

    # If a real .env exists in the repo, it must not still hold live-looking keys.
    env_file = _REPO / ".env"
    if env_file.exists():
        text = env_file.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"(OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*=\s*sk-[A-Za-z0-9]", text), (
            "on-disk .env still contains a live-looking API key — rotate + scrub it"
        )
