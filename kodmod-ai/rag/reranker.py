"""
KODMOD AI — Cross-Encoder Reranker
==================================

Bi-encoder retrieval (BGE-M3) is fast but imperfect; a cross-encoder
sees query + doc together and re-orders the candidate set with much
higher precision. We use BGE-reranker-v2-m3 (multilingual, ID-friendly).

Loaded lazily and pinned to GPU when available. Falls back gracefully:
when the reranker model can't be loaded (offline, no GPU memory), we
return the bi-encoder ordering unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Optional, Sequence

from config.settings import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        logger.info("Loading reranker model %s", settings.RERANKER_MODEL)
        return CrossEncoder(settings.RERANKER_MODEL, max_length=512)
    except Exception as exc:
        logger.warning("Reranker unavailable, falling back to bi-encoder order: %s", exc)
        return None


async def rerank(
    query: str,
    docs: Sequence[dict],
    *,
    top_k: Optional[int] = None,
    text_key: str = "text",
) -> list[dict]:
    """
    Re-order `docs` by cross-encoder relevance to `query`.
    Each input doc must carry the chunk text under `text_key`.

    Returns at most `top_k` docs (defaults to settings.RAG_RERANK_TOP_K).
    """
    if not docs:
        return []
    top_k = top_k or settings.RAG_RERANK_TOP_K
    model = _load_model()
    if model is None:
        return list(docs[:top_k])

    pairs = [(query, d.get(text_key, "")) for d in docs]
    loop = asyncio.get_running_loop()

    def _score():
        return model.predict(pairs, convert_to_numpy=True)

    scores = await loop.run_in_executor(None, _score)
    enriched = []
    for d, s in zip(docs, scores):
        d2 = dict(d)
        d2["rerank_score"] = float(s)
        enriched.append(d2)
    enriched.sort(key=lambda x: x["rerank_score"], reverse=True)
    return enriched[:top_k]
