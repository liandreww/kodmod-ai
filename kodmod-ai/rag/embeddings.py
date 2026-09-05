"""
KODMOD AI — Embeddings
======================

Wraps OpenAI's embedding model for both retrieval indexing and query-time
embedding. `text-embedding-3-small` handles Indonesian and English well, and
at its native 1536 dimensions it sits comfortably under pgvector's 2000-dim
ANN index limit, so no truncation is needed.

The client is built lazily and memoized; callers `await embed_text([...])`.
Both the model id and the dimension come from settings, so index-time and
query-time vectors can never drift apart.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache

from config.settings import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client():
    from langchain_openai import OpenAIEmbeddings

    opts: dict = {
        "model": settings.EMBEDDING_MODEL,
        "dimensions": settings.EMBEDDING_DIM,
    }
    if settings.OPENAI_API_KEY:
        opts["api_key"] = settings.OPENAI_API_KEY
    if settings.OPENAI_BASE_URL:
        opts["base_url"] = settings.OPENAI_BASE_URL
    return OpenAIEmbeddings(**opts)


def reset_embeddings_cache() -> None:
    """Drop the memoized client. Call after changing embedding settings in tests."""
    _client.cache_clear()


async def embed_text(texts: Sequence[str]) -> list[list[float]]:
    """Embed a list of texts. The OpenAI client is natively async, no threadpool needed."""
    if not texts:
        return []
    return await _client().aembed_documents(list(texts))
