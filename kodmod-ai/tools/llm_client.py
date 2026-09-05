"""
KODMOD AI — LLM Client Factory
===============================

Single point where models are configured. Different agents use different
models based on cost / latency / quality trade-offs:

| Agent              | Role getter                | Why                       |
|--------------------|----------------------------|---------------------------|
| Intent Router      | get_router_llm             | Classification, must be fast |
| Tutoring Agent     | get_tutor_llm              | Quality matters most; streaming |
| Quiz / Problem Gen | get_quiz_llm               | Structured JSON output    |
| Scoring Agent      | get_scoring_llm            | Rubric grading, deterministic |
| Recommendation     | get_recommendation_llm     | Short JSON output         |
| Reflection         | get_reflection_llm         | Quality gate on every turn |

OpenAI is the only provider. Which model backs each role is decided entirely
by `.env` (`LLM_*_MODEL`); nothing is hardcoded here. Never instantiate
`ChatOpenAI` directly in agent code — always go through a getter.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from config.settings import MODEL_UNSET, settings


class ModelNotConfiguredError(RuntimeError):
    """Raised when a role's model id was never supplied via the environment."""


def language_instruction() -> str:
    """Appended to the end of every agent's system prompt.

    Read fresh on every call (never baked into a module-level prompt
    constant) so `GRAPH_LANGUAGE` can be changed via `.env` without a code
    change, and so tests can monkeypatch it. Placed last in the prompt
    deliberately — it's the model's most recent instruction, so it overrides
    whatever language the input, retrieved curriculum, or few-shot examples
    happen to be in.
    """
    return (
        f"\n\nIMPORTANT: Always respond in {settings.GRAPH_LANGUAGE}, no matter what "
        "language the student's input, the curriculum context, or any examples above "
        "are written in."
    )


def _resolve(env_key: str) -> str:
    """Return the configured model id for `env_key`, or fail with a clear message."""
    model = getattr(settings, env_key, MODEL_UNSET)
    if not model or model == MODEL_UNSET:
        raise ModelNotConfiguredError(
            f"{env_key} is not set. Add `{env_key}=<openai-model-id>` to your .env "
            f"before starting the app."
        )
    return str(model)


def _chat(model: str, **kwargs: Any):
    """Build a LangChain chat model backed by OpenAI."""
    from langchain_openai import ChatOpenAI

    opts: dict[str, Any] = {
        "model": model,
        "temperature": kwargs.get("temperature", 0.4),
        "max_tokens": kwargs.get("max_tokens", 1024),
        "streaming": kwargs.get("streaming", True),
    }
    if settings.OPENAI_API_KEY:
        opts["api_key"] = settings.OPENAI_API_KEY
    if settings.OPENAI_BASE_URL:
        opts["base_url"] = settings.OPENAI_BASE_URL
    return ChatOpenAI(**opts)  # type: ignore[arg-type]  # valid runtime kwargs; stub is stricter


# ---------------------------------------------------------------------------
# Per-role getters (memoized so we don't re-instantiate per request)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_router_llm():
    """Fast and small: intent classification on every turn."""
    return _chat(_resolve("LLM_ROUTER_MODEL"), temperature=0.0, max_tokens=256, streaming=False)


@lru_cache(maxsize=1)
def get_tutor_llm():
    """Best quality, streaming on — this is what the student actually hears."""
    return _chat(_resolve("LLM_TUTOR_MODEL"), temperature=0.5, max_tokens=1500, streaming=True)


@lru_cache(maxsize=1)
def get_quiz_llm():
    return _chat(_resolve("LLM_QUIZ_MODEL"), temperature=0.3, max_tokens=2048, streaming=False)


@lru_cache(maxsize=1)
def get_scoring_llm():
    return _chat(_resolve("LLM_SCORING_MODEL"), temperature=0.0, max_tokens=512, streaming=False)


@lru_cache(maxsize=1)
def get_recommendation_llm():
    return _chat(
        _resolve("LLM_RECOMMENDATION_MODEL"), temperature=0.3, max_tokens=768, streaming=False
    )


@lru_cache(maxsize=1)
def get_reflection_llm():
    return _chat(_resolve("LLM_REFLECTION_MODEL"), temperature=0.0, max_tokens=512, streaming=False)


_GETTERS = (
    get_router_llm,
    get_tutor_llm,
    get_quiz_llm,
    get_scoring_llm,
    get_recommendation_llm,
    get_reflection_llm,
)


def reset_llm_cache() -> None:
    """Drop every memoized client. Call after changing model settings in tests."""
    for getter in _GETTERS:
        getter.cache_clear()
