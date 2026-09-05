"""
KODMOD AI — RAG Tool
====================

Single retrieval interface used by:
* Tutoring Agent (curriculum grounding)
* Problem Generator (question-grounding)
* Content Retrieval Agent (cluster 3)

Pipeline
--------
    query → embed → vector search (pgvector) → rerank (cross-encoder)
          → metadata filter → return top-K chunks

Configuration
-------------
* Vector store: pgvector.
* Embedding model: OpenAI `text-embedding-3-small` (see `settings.EMBEDDING_MODEL`).
* Reranker: BGE-reranker-v2-m3 (cross-encoder, runs locally).

Two retrieval modes
-------------------
* `retrieve()`     — returns dicts (used as a normal Python tool)
* `as_langchain_tool()` — returns a LangChain `Tool` for agents that bind tools
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import Tool

from config.settings import settings
from graphs.state import RetrievedDoc
from rag.embeddings import embed_text
from rag.reranker import rerank

log = logging.getLogger(__name__)


class RAGTool:
    """Curriculum & content retriever."""

    def __init__(self, top_k_vector: int = 20, top_k_final: int = 5):
        self.top_k_vector = top_k_vector
        self.top_k_final = top_k_final
        self._store = self._build_store()

    # -----------------------------------------------------------------
    def _build_store(self):
        from rag.stores.pgvector_store import PgVectorStore

        return PgVectorStore()

    # -----------------------------------------------------------------
    async def retrieve(
        self,
        query: str,
        k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedDoc]:
        """Retrieve top-K curriculum chunks for `query`."""
        if not query.strip():
            return []
        k = k or self.top_k_final

        # 1. Embed
        [vec] = await embed_text([query])

        # 2. Vector search
        candidates = await self._store.similarity_search(
            embedding=vec,
            top_k=self.top_k_vector,
            filters=filters or {},
        )

        if not candidates:
            return []

        # 3. Cross-encoder rerank for precision (optional — the bi-encoder
        # order from the vector search is already decent, so this can be
        # switched off when the extra local model isn't worth the weight).
        if settings.RAG_RERANK_ENABLED:
            reranked = await rerank(query, candidates, top_k=k)
        else:
            reranked = candidates[:k]

        log.info(
            "RAG: query='%s' retrieved=%d returned=%d", query[:50], len(candidates), len(reranked)
        )

        return [
            RetrievedDoc(
                doc_id=c.get("doc_id", ""),
                chunk_id=c.get("chunk_id", ""),
                text=c.get("text", ""),
                score=float(c.get("rerank_score", c.get("score", 0.0))),
                source=c.get("source", "curriculum"),
                concept_ids=c.get("concept_ids", []),
            )
            for c in reranked
        ]

    # -----------------------------------------------------------------
    def as_langchain_tool(self) -> Tool:
        async def _arun(query: str) -> str:
            docs = await self.retrieve(query)
            return "\n---\n".join(f"[{d['source']}] {d['text']}" for d in docs)

        return Tool(  # type: ignore[call-arg]  # async-only Tool: coroutine set, func omitted
            name="curriculum_search",
            description=(
                "Search the KODMOD curriculum knowledge base. "
                "Input: a natural-language query. Output: top relevant text chunks."
            ),
            coroutine=_arun,
        )
