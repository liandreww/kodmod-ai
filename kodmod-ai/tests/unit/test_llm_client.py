"""KM-UNIT-130..135 — per-role LLM getters (tools/llm_client.py).

OpenAI is the only provider. Each getter is `@lru_cache`d, takes no arguments,
and reads its model id from settings, so these tests patch
`langchain_openai.ChatOpenAI` to capture what would have been constructed and
call `reset_llm_cache()` afterwards so one test cannot leak into the next.

Spec: docs/testplan/01-unit.md §9.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

import tools.llm_client as llm_client
from config.settings import MODEL_UNSET

pytestmark = [pytest.mark.unit, pytest.mark.no_llm_stub]


class _RecordingChatOpenAI:
    """Stands in for ChatOpenAI and records the kwargs it was built with."""

    last_kwargs: ClassVar[dict[str, object]] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = dict(kwargs)

    async def ainvoke(self, *_a: object, **_k: object) -> None: ...

    async def astream(self, *_a: object, **_k: object) -> None: ...


@pytest.fixture(autouse=True)
def _clear_getter_caches():
    llm_client.reset_llm_cache()
    yield
    llm_client.reset_llm_cache()


@pytest.fixture
def recording_openai(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingChatOpenAI]:
    langchain_openai = pytest.importorskip("langchain_openai")
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _RecordingChatOpenAI)
    return _RecordingChatOpenAI


def test_getter_returns_runnable_model(recording_openai) -> None:  # KM-UNIT-130
    model = llm_client.get_tutor_llm()
    assert hasattr(model, "ainvoke")
    assert hasattr(model, "astream")


def test_each_role_uses_its_own_configured_model(  # KM-UNIT-131
    recording_openai, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A role must read its own LLM_*_MODEL, not another role's."""
    monkeypatch.setattr(llm_client.settings, "LLM_ROUTER_MODEL", "model-for-router")
    monkeypatch.setattr(llm_client.settings, "LLM_TUTOR_MODEL", "model-for-tutor")

    llm_client.get_router_llm()
    assert recording_openai.last_kwargs["model"] == "model-for-router"

    llm_client.get_tutor_llm()
    assert recording_openai.last_kwargs["model"] == "model-for-tutor"


def test_role_kwargs_differ(recording_openai) -> None:  # KM-UNIT-132
    """The tutor streams and is allowed to be discursive; the router is neither."""
    llm_client.get_tutor_llm()
    tutor = dict(recording_openai.last_kwargs)
    llm_client.get_router_llm()
    router = dict(recording_openai.last_kwargs)

    assert tutor["streaming"] is True
    assert router["streaming"] is False
    assert router["temperature"] == 0.0
    assert tutor["max_tokens"] > router["max_tokens"]


def test_base_url_is_forwarded_when_set(  # KM-UNIT-133
    recording_openai, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test stack points every call at an OpenAI-compatible stub this way."""
    monkeypatch.setattr(llm_client.settings, "OPENAI_BASE_URL", "http://stub:8099/v1")
    llm_client.get_quiz_llm()
    assert recording_openai.last_kwargs["base_url"] == "http://stub:8099/v1"


def test_unset_model_raises_a_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # KM-UNIT-134
    monkeypatch.setattr(llm_client.settings, "LLM_SCORING_MODEL", MODEL_UNSET)
    with pytest.raises(llm_client.ModelNotConfiguredError) as exc:
        llm_client.get_scoring_llm()
    assert "LLM_SCORING_MODEL" in str(exc.value)


def test_getter_rejects_arguments() -> None:  # KM-UNIT-135
    with pytest.raises(TypeError):
        llm_client.get_tutor_llm(temperature=0.2)  # type: ignore[call-arg]
