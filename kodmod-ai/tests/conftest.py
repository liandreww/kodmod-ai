"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio
import os

import pytest

# Ensure tests use a separate env (no real API calls, no real DB writes).
os.environ.setdefault("ENV", "test")
os.environ.setdefault("KODMOD_LLM_PROVIDER", "anthropic")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DB_NAME", "kodmod_test")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so async fixtures share state."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
