"""
KODMOD AI — Embeddings
======================

Wraps BGE-M3 (multilingual, dense + sparse) for both retrieval indexing and
query-time embedding. BGE-M3 was chosen because:

* Strong on Indonesian + English (KODMOD's primary languages).
* 1024-dim dense vectors fit pgvector indexes efficiently.
* Sparse + dense hybrid retrieval gives the best results on educational
  Q&A (vs. e.g. text-embedding-3-small).

The actual model is loaded lazily; callers `await embed_text([...])`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from functools import lru_cache

log = logging.getLogger(__name__)

EMBED_DIM = int(os.getenv("KODMOD_EMBED_DIM", "1024"))


@lru_cache(maxsize=1)
def _model():
    """Load BGE-M3 once. Falls back to OpenAI embeddings if specified."""
    backend = os.getenv("KODMOD_EMBED_BACKEND", "bge-m3")
    if backend == "openai":
        from langchain_openai import OpenAIEmbeddings

        model = os.getenv("KODMOD_EMBED_MODEL", "text-embedding-3-small")
        # Truncate to EMBED_DIM so vectors match the pgvector column (vector(1024))
        # and stay under pgvector's 2000-dim ANN index limit.
        return ("openai", OpenAIEmbeddings(model=model, dimensions=EMBED_DIM))

    # Default: FlagEmbedding's BGE-M3
    try:
        from FlagEmbedding import BGEM3FlagModel

        m = BGEM3FlagModel(
            "BAAI/bge-m3",
            use_fp16=True,
            device=os.getenv("KODMOD_EMBED_DEVICE", "cuda"),
        )
        return ("bge", m)
    except ImportError:
        log.warning("FlagEmbedding not installed; falling back to sentence-transformers")
        from sentence_transformers import SentenceTransformer

        m = SentenceTransformer("BAAI/bge-m3")
        return ("st", m)


async def embed_text(texts: Sequence[str]) -> list[list[float]]:
    """
    Embed a list of texts. Async-friendly: heavy CPU/GPU work is run in a
    threadpool so the event loop isn't blocked.
    """
    if not texts:
        return []
    backend, m = _model()

    def _run() -> list[list[float]]:
        if backend == "openai":
            return m.embed_documents(list(texts))
        if backend == "bge":
            out = m.encode(
                list(texts),
                batch_size=16,
                max_length=1024,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            return out["dense_vecs"].tolist()
        # sentence-transformers
        return m.encode(list(texts), normalize_embeddings=True).tolist()

    loop = asyncio.get_running_loop()
    vectors = await loop.run_in_executor(None, _run)
    return vectors
