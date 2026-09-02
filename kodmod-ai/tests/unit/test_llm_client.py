"""KM-UNIT-130..134 — per-role LLM getters (tools/llm_client.py).

The getters are `@lru_cache`d and take no arguments; provider is chosen by the
KODMOD_LLM_PROVIDER env var. We patch `_FACTORIES` (and, for vllm, the
`langchain_openai.ChatOpenAI` symbol) and always `cache_clear()` afterwards so
one test can't leak a stubbed model into the next.

Spec: docs/testplan/01-unit.md §9.
"""

from __future__ import annotations

import pytest

import tools.llm_client as llm_client
from tests._fakes.fake_chat import make_fake_chat

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_getter_caches():
    yield
    for name in (
        "get_router_llm",
        "get_tutor_llm",
        "get_quiz_llm",
        "get_scoring_llm",
        "get_recommendation_llm",
    ):
        getattr(llm_client, name).cache_clear()


def test_getter_returns_runnable_model(monkeypatch: pytest.MonkeyPatch) -> None:  # KM-UNIT-130
    monkeypatch.setitem(
        llm_client._FACTORIES, "anthropic", lambda *_a, **_k: make_fake_chat("tutor")
    )
    llm_client.get_tutor_llm.cache_clear()
    model = llm_client.get_tutor_llm()
    assert hasattr(model, "ainvoke")
    assert hasattr(model, "astream")


def test_provider_switch_selects_factory(monkeypatch: pytest.MonkeyPatch) -> None:  # KM-UNIT-131
    used: list[str] = []
    for key in list(llm_client._FACTORIES):
        monkeypatch.setitem(
            llm_client._FACTORIES,
            key,
            lambda *_a, _k=key, **_kw: used.append(_k) or make_fake_chat("router"),
        )
    monkeypatch.setenv("KODMOD_LLM_PROVIDER", "openai")
    llm_client.get_router_llm.cache_clear()
    llm_client.get_router_llm()
    assert used == ["openai"]


def test_recommendation_llm_is_quiz_llm(monkeypatch: pytest.MonkeyPatch) -> None:  # KM-UNIT-132
    monkeypatch.setitem(
        llm_client._FACTORIES, "anthropic", lambda *_a, **_k: make_fake_chat("quiz")
    )
    llm_client.get_quiz_llm.cache_clear()
    llm_client.get_recommendation_llm.cache_clear()
    assert llm_client.get_recommendation_llm() is llm_client.get_quiz_llm()


def test_getter_rejects_arguments() -> None:  # KM-UNIT-133
    with pytest.raises(TypeError):
        llm_client.get_tutor_llm(temperature=0.2)  # type: ignore[call-arg]


def test_vllm_uses_empty_api_key_and_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # KM-UNIT-134
    langchain_openai = pytest.importorskip("langchain_openai")
    captured: dict[str, object] = {}

    class _RecordingChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _RecordingChatOpenAI)
    monkeypatch.setenv("KODMOD_LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_BASE_URL", "http://test-vllm:9000/v1")
    llm_client.get_router_llm.cache_clear()
    llm_client.get_router_llm()
    assert captured["api_key"] == "EMPTY"
    assert captured["base_url"] == "http://test-vllm:9000/v1"
