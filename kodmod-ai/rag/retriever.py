"""
KODMOD AI — RAG Retriever (orchestration layer)
===============================================

Single entry point used by `tools/rag_tool.py` and the LangGraph
`rag_retrieval_node`. Selects the configured backend, embeds the query,
performs vector search, and runs the cross-encoder reranker.

This module is intentionally thin — it composes:
    embeddings.embed_text  +  stores.<backend>.query  +  reranker.rerank
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from config.settings import settings
from rag.embeddings import embed_text
from rag.reranker import rerank

logger = logging.getLogger(__name__)


def _store():
    """Lazy import of the configured backend so missing optional deps don't break startup."""
    if settings.VECTOR_BACKEND == "qdrant":
        from rag.stores import qdrant_store as _s
    else:
        from rag.stores import pgvector_store as _s
    return _s


async def retrieve(
    query: str,
    *,
    concept_id: Optional[uuid.UUID] = None,
    language: Optional[str] = None,
    top_k: Optional[int] = None,
    rerank_top_k: Optional[int] = None,
    use_reranker: bool = True,
) -> list[dict]:
    """
    Returns ranked chunks: list of dicts with keys
    `id, text, source, section_title, score, rerank_score (opt), accessibility_metadata`.
    """
    if not query.strip():
        return []
    top_k = top_k or settings.RAG_TOP_K
    rerank_top_k = rerank_top_k or settings.RAG_RERANK_TOP_K

    embedding = await embed_text(query)
    candidates = await _store().query(
        embedding,
        top_k=top_k,
        concept_id=concept_id,
        language=language or settings.DEFAULT_LANGUAGE,
    )
    if not candidates:
        return []

    if use_reranker and len(candidates) > rerank_top_k:
        return await rerank(query, candidates, top_k=rerank_top_k)
    return candidates[:rerank_top_k]


# ---------------------------------------------------------------------------
# LangGraph node — used directly from `graphs/main_graph.py`
# ---------------------------------------------------------------------------
async def rag_retrieval_node(state) -> dict:
    """
    LangGraph node wrapping `retrieve()`. Reads the latest student
    utterance from `state["transcribed_text"]` (or, if missing, the last
    HumanMessage), retrieves grounding chunks, and writes them into
    `state["retrieved_docs"]`.
    """
    query = state.get("transcribed_text") or ""
    if not query and state.get("messages"):
        # Fall back to the most recent HumanMessage content.
        for m in reversed(state["messages"]):
            try:
                role = getattr(m, "type", None) or getattr(m, "role", None)
                if role in {"human", "user"}:
                    query = getattr(m, "content", "") or ""
                    break
            except Exception:
                continue

    if not query.strip():
        return {"retrieved_docs": []}

    concept_id = None
    if cid := state.get("concept_id"):
        try:
            import uuid as _uuid
            concept_id = _uuid.UUID(str(cid))
        except (ValueError, TypeError):
            concept_id = None

    docs = await retrieve(
        query,
        concept_id=concept_id,
        language=state.get("learning_profile", {}).get("preferred_language"),
    )
    logger.info("RAG retrieved %d chunks for query=%r", len(docs), query[:64])
    return {"retrieved_docs": docs}
