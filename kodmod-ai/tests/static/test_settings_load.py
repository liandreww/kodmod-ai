"""KM-STATIC-012..015 — config.settings loads safely.

Each case runs in a **child process** with a controlled env and cwd=tmp_path so
neither the repo's on-disk ``.env`` nor the pytest-session env forced by
tests/conftest.py leaks into the cached ``settings`` singleton.

Oracle: pydantic-settings + config/settings.py (the ``enable_decoding=False`` /
``_split_origins`` fix for L-16, and the DSN ``@property`` shapes).
"""

from __future__ import annotations

import shutil
import sys

import pytest

from tests.static._util import PROJECT_ROOT, minimal_env, out, run

pytestmark = pytest.mark.static


def _run_py(code: str, tmp_path, **env: str):
    return run([sys.executable, "-c", code], env=minimal_env(**env), cwd=tmp_path)


def test_settings_load_clean_env(tmp_path) -> None:  # KM-STATIC-012
    proc = _run_py("from config.settings import settings; print(settings.ENV)", tmp_path)
    assert proc.returncode == 0, out(proc)
    assert proc.stdout.strip().splitlines()[-1] == "dev"


def test_settings_load_dotenv_example(tmp_path) -> None:  # KM-STATIC-013
    shutil.copy(PROJECT_ROOT / ".env.example", tmp_path / ".env")
    proc = _run_py(
        "from config.settings import settings; "
        "print(settings.ENV); print(settings.CORS_ALLOW_ORIGINS)",
        tmp_path,
    )
    assert proc.returncode == 0, out(proc)
    assert "SettingsError" not in (proc.stderr or "")
    assert "ValidationError" not in (proc.stderr or "")
    tail = proc.stdout.strip().splitlines()
    assert tail[-2] == "dev"
    # The comma-split validator ran and no JSON decode was attempted. The value
    # is an explicit origin list: "*" is invalid alongside allow_credentials.
    assert tail[-1] == "['http://localhost:3000', 'http://127.0.0.1:3000']"


def test_settings_load_provider_openai(tmp_path) -> None:  # KM-STATIC-014
    proc = _run_py(
        "import config.settings, tools.llm_client; print('ok')",
        tmp_path,
        KODMOD_LLM_PROVIDER="openai",
        OPENAI_API_KEY="x",
    )
    assert proc.returncode == 0, out(proc)
    assert proc.stdout.strip().splitlines()[-1] == "ok"


def test_settings_dsn_properties(tmp_path) -> None:  # KM-STATIC-015
    proc = _run_py(
        "from config.settings import settings; "
        "print(settings.DATABASE_URL); print(settings.LANGGRAPH_DB_URI)",
        tmp_path,
    )
    assert proc.returncode == 0, out(proc)
    db_url, lg_uri = proc.stdout.strip().splitlines()[-2:]
    assert db_url.startswith("postgresql+asyncpg://")
    assert lg_uri.startswith("postgresql://")
    assert "+asyncpg" not in lg_uri
