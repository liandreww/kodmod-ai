"""KM-UNIT-150..152 — pure RAG helpers with no I/O.

Oracle: graceful-degradation branch in rag/reranker.rerank, the pgvector literal
formatter, and the empty-input fast path of rag.embeddings.embed_text.

Spec: docs/testplan/01-unit.md §11.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


async def test_rerank_passthrough_when_model_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # KM-UNIT-150
    import rag.reranker as reranker

    monkeypatch.setattr(reranker, "_load_model", lambda: None)
    docs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    out = await reranker.rerank("q", docs, top_k=2)
    assert out == docs[:2]  # original order, first top_k
    assert all("rerank_score" not in d for d in out)


def test_vec_literal_formats_seven_decimals() -> None:  # KM-UNIT-151
    from rag.stores.pgvector_store import _vec_literal

    assert _vec_literal([0.123456789, 1.0]) == "[0.1234568,1.0000000]"


async def test_embed_text_empty_input_no_model_load() -> None:  # KM-UNIT-152
    from rag.embeddings import embed_text

    assert await embed_text([]) == []
