"""
KODMOD AI — LLM Client Factory
===============================

Single point where models are configured. Different agents use different
models based on cost / latency / quality trade-offs:

| Agent              | Model class    | Why                                 |
|--------------------|----------------|-------------------------------------|
| Intent Router      | small / fast   | Classification, < 200 ms            |
| Tutoring Agent     | flagship       | Quality matters most; streaming     |
| Quiz / Problem Gen | flagship-mini  | Structured JSON, mid-quality        |
| Scoring Agent      | flagship-mini  | Rubric grading                      |
| Quiz Analyzer      | flagship       | Pattern detection, nuanced          |
| Recommendation     | flagship-mini  | Short JSON output                   |
| Reflection         | small / fast   | Quality gate, runs on every turn    |

All models are wrapped in LangChain's chat-model abstraction so we can swap
providers without touching agent code. Set `KODMOD_LLM_PROVIDER` env var to
choose: `anthropic` | `openai` | `ollama` | `vllm`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any


def _provider() -> str:
    return os.getenv("KODMOD_LLM_PROVIDER", "anthropic").lower()


# ---------------------------------------------------------------------------
# Anthropic-backed factory (default)
# ---------------------------------------------------------------------------

def _anthropic(model: str, **kwargs: Any):
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=model,
        temperature=kwargs.get("temperature", 0.4),
        max_tokens=kwargs.get("max_tokens", 1024),
        streaming=kwargs.get("streaming", True),
    )


def _openai(model: str, **kwargs: Any):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        temperature=kwargs.get("temperature", 0.4),
        max_tokens=kwargs.get("max_tokens", 1024),
        streaming=kwargs.get("streaming", True),
    )


def _ollama(model: str, **kwargs: Any):
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=model,
        temperature=kwargs.get("temperature", 0.4),
        num_predict=kwargs.get("max_tokens", 1024),
    )


def _vllm(model: str, **kwargs: Any):
    """For self-hosted vLLM endpoints, use the OpenAI-compatible client."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        base_url=os.getenv("VLLM_BASE_URL", "http://vllm:8000/v1"),
        api_key="EMPTY",
        temperature=kwargs.get("temperature", 0.4),
        max_tokens=kwargs.get("max_tokens", 1024),
        streaming=kwargs.get("streaming", True),
    )


_FACTORIES = {
    "anthropic": _anthropic,
    "openai": _openai,
    "ollama": _ollama,
    "vllm": _vllm,
}


# ---------------------------------------------------------------------------
# Per-role getters (memoized so we don't re-instantiate per request)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_router_llm():
    """Fast, small. ~200 ms target."""
    p = _provider()
    model = {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai":    "gpt-4o-mini",
        "ollama":    "llama3.1:8b",
        "vllm":      "meta-llama/Meta-Llama-3.1-8B-Instruct",
    }[p]
    return _FACTORIES[p](model, temperature=0.0, max_tokens=256, streaming=False)


@lru_cache(maxsize=1)
def get_tutor_llm():
    """Flagship quality, streaming on."""
    p = _provider()
    model = {
        "anthropic": "claude-opus-4-7",
        "openai":    "gpt-4.1",
        "ollama":    "llama3.1:70b",
        "vllm":      "meta-llama/Meta-Llama-3.1-70B-Instruct",
    }[p]
    return _FACTORIES[p](model, temperature=0.5, max_tokens=1500, streaming=True)


@lru_cache(maxsize=1)
def get_quiz_llm():
    p = _provider()
    model = {
        "anthropic": "claude-sonnet-4-6",
        "openai":    "gpt-4.1-mini",
        "ollama":    "qwen2.5:14b",
        "vllm":      "Qwen/Qwen2.5-14B-Instruct",
    }[p]
    return _FACTORIES[p](model, temperature=0.3, max_tokens=2048, streaming=False)


@lru_cache(maxsize=1)
def get_scoring_llm():
    p = _provider()
    model = {
        "anthropic": "claude-sonnet-4-6",
        "openai":    "gpt-4.1-mini",
        "ollama":    "qwen2.5:14b",
        "vllm":      "Qwen/Qwen2.5-14B-Instruct",
    }[p]
    return _FACTORIES[p](model, temperature=0.0, max_tokens=512, streaming=False)


@lru_cache(maxsize=1)
def get_recommendation_llm():
    return get_quiz_llm()
