"""
KODMOD AI — RAG Retriever (orchestration layer)
===============================================

Single entry point used by `tools/rag_tool.py` and the LangGraph
`rag_retrieval_node`. Embeds the query, performs the pgvector search, and runs
the cross-encoder reranker.

This module is intentionally thin — it composes:
    embeddings.embed_text  +  pgvector_store.query  +  reranker.rerank
"""

from __future__ import annotations

import logging
import uuid

from config.settings import settings
from rag.embeddings import embed_text
from rag.reranker import rerank
from rag.stores import pgvector_store

logger = logging.getLogger(__name__)


async def retrieve(
    query: str,
    *,
    concept_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
    language: str | None = None,
    top_k: int | None = None,
    rerank_top_k: int | None = None,
    use_reranker: bool | None = None,
) -> list[dict]:
    """
    Returns ranked chunks: list of dicts with keys
    `id, text, source, section_title, score, rerank_score (opt), accessibility_metadata`.
    """
    if not query.strip():
        return []
    top_k = top_k or settings.RAG_TOP_K
    rerank_top_k = rerank_top_k or settings.RAG_RERANK_TOP_K
    if use_reranker is None:
        use_reranker = settings.RAG_RERANK_ENABLED

    embedding = (await embed_text([query]))[0]
    candidates = await pgvector_store.query(
        embedding,
        top_k=top_k,
        concept_id=concept_id,
        subject_id=subject_id,
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
    utterance from `state["user_input"]` (or, if missing, the last
    HumanMessage), retrieves grounding chunks scoped to the selected subject,
    and writes them into `state["retrieved_docs"]`.
    """
    query = state.get("user_input") or ""
    if not query and state.get("messages"):
        # Fall back to the most recent HumanMessage content.
        for m in reversed(state["messages"]):
            try:
                role = getattr(m, "type", None) or getattr(m, "role", None)
                if role in {"human", "user"}:
                    query = getattr(m, "content", "") or ""
                    break
            except Exception:  # noqa: S112  # skip malformed message entries, keep scanning history
                continue

    if not query.strip():
        return {"retrieved_docs": [], "next_action": "tutor", "last_node": "rag_retrieval"}

    docs = await retrieve(
        query,
        concept_id=_as_uuid(state.get("current_concept_id")),
        subject_id=_as_uuid(state.get("subject_id")),
        language=state.get("learning_profile", {}).get("language"),
    )
    logger.info("RAG retrieved %d chunks for query=%r", len(docs), query[:64])
    return {"retrieved_docs": docs, "next_action": "tutor", "last_node": "rag_retrieval"}


def _as_uuid(value) -> uuid.UUID | None:
    """Coerce a state value to a UUID, or None when it is absent or malformed."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
