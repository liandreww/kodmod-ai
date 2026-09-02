"""Stage 3 §8 — rag/retriever.py + rag/ingestion.py (real pgvector, stub embeddings).

Spec: docs/testplan/03-integration.md §8 (KM-INT-091..098).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

from tests._fakes.fake_embeddings import fake_embed_text_sync

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]

CID = str(uuid.UUID("55555555-5555-5555-5555-5555555555aa"))


def _rec(text: str, idx: int = 0, *, cid: str = CID, language: str = "id", src: str = "ret.md"):
    return {
        "id": str(uuid.uuid4()),
        "text": text,
        "embedding": fake_embed_text_sync([text])[0],
        "source": src,
        "language": language,
        "concept_id": cid,
        "chunk_index": idx,
        "section_title": None,
        "accessibility_metadata": {},
    }


# --------------------------------------------------------------------------- #
# KM-INT-091 — node contract: reads current_concept_id, sets next_action  (#10)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#10 — rag_retrieval_node reads state['concept_id'] (never set) instead of "
    "state['current_concept_id'], and returns only {'retrieved_docs': ...} without "
    "next_action / last_node"
)
async def test_km_int_091_rag_node_contract(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.retriever import rag_retrieval_node
    from rag.stores import pgvector_store as store

    await store.upsert_chunks([_rec("pecahan adalah bagian dari keseluruhan", 0)])
    state = {"transcribed_text": "apa itu pecahan", "current_concept_id": CID}
    out = await rag_retrieval_node(state)

    assert out.get("retrieved_docs")  # some grounding came back
    assert out.get("next_action"), "node must advance next_action"
    assert out.get("last_node") == "rag_retrieval"


# --------------------------------------------------------------------------- #
# KM-INT-092 — retrieve("") short-circuits to []
# --------------------------------------------------------------------------- #
async def test_km_int_092_empty_query(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.retriever import retrieve

    assert await retrieve("") == []
    assert await retrieve("   ") == []


# --------------------------------------------------------------------------- #
# KM-INT-093 — end-to-end retrieve returns relevant chunks, capped at rerank_top_k
# --------------------------------------------------------------------------- #
async def test_km_int_093_retrieve_end_to_end(clean_db) -> None:  # type: ignore[no-untyped-def]
    from config.settings import settings
    from rag.retriever import retrieve
    from rag.stores import pgvector_store as store

    texts = [
        "pecahan adalah bagian dari keseluruhan",
        "pecahan senilai memiliki nilai sama",
        "menjumlahkan pecahan berpenyebut sama",
        "tata surya memiliki delapan planet",
        "fotosintesis terjadi di daun",
        "kalimat efektif itu ringkas",
    ]
    await store.upsert_chunks([_rec(t, i) for i, t in enumerate(texts)])

    res = await retrieve("pecahan adalah bagian dari keseluruhan", top_k=6)
    assert res
    assert len(res) <= settings.RAG_RERANK_TOP_K
    assert res[0]["text"] == "pecahan adalah bagian dari keseluruhan"


# --------------------------------------------------------------------------- #
# KM-INT-094 — reranker passthrough when the model can't load
# --------------------------------------------------------------------------- #
async def test_km_int_094_reranker_passthrough(clean_db) -> None:  # type: ignore[no-untyped-def]
    # stub_reranker (autouse) already forces _load_model() -> None.
    from config.settings import settings
    from rag import retriever
    from rag.stores import pgvector_store as store

    await store.upsert_chunks([_rec(f"pecahan varian {i}", i) for i in range(6)])
    res = await retriever.retrieve("pecahan varian 0", top_k=6)
    assert len(res) == settings.RAG_RERANK_TOP_K  # candidates[:rerank_top_k], order preserved


# --------------------------------------------------------------------------- #
# KM-INT-095 — no candidates -> []
# --------------------------------------------------------------------------- #
async def test_km_int_095_no_candidates(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.retriever import retrieve

    assert await retrieve("konsep yang tidak pernah ada di store", top_k=5) == []


# --------------------------------------------------------------------------- #
# KM-INT-096 — ingest_paths on a mini markdown doc
# --------------------------------------------------------------------------- #
async def test_km_int_096_ingest_paths(clean_db, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text as sa_text

    from database.session import async_session
    from rag.ingestion import ingest_paths

    doc = tmp_path / "pecahan_mini.md"
    doc.write_text(
        "# Pengertian Pecahan\n\n"
        "Pecahan adalah bilangan yang menyatakan bagian dari keseluruhan. "
        "Pembilang di atas, penyebut di bawah, penyebut tidak boleh nol.\n\n"
        "## Membandingkan Pecahan\n\n"
        "Samakan penyebut lalu bandingkan pembilang. Lihat Gambar 1 untuk ilustrasi.\n",
        encoding="utf-8",
    )
    n = await ingest_paths([doc], concept_id=uuid.UUID(CID), language="id")
    assert n > 0
    async with async_session() as s:
        rows = (
            (
                await s.execute(
                    sa_text(
                        "SELECT vector_dims(embedding) AS d FROM curriculum_chunks WHERE source LIKE :src"
                    ),
                    {"src": f"%{doc.name}"},
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == n
    assert all(d == 1024 for d in rows)


# --------------------------------------------------------------------------- #
# KM-INT-097 — PDF ingest without pypdf degrades to "" (no crash)
# --------------------------------------------------------------------------- #
def test_km_int_097_pdf_without_pypdf(monkeypatch, tmp_path) -> None:
    from rag.ingestion import _load_text

    monkeypatch.setitem(sys.modules, "pypdf", None)  # -> `import pypdf` raises ImportError
    fake_pdf = tmp_path / "x.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 not really")
    assert _load_text(Path(fake_pdf)) == ""


# --------------------------------------------------------------------------- #
# KM-INT-098 — _store() selects the configured backend
# --------------------------------------------------------------------------- #
def test_km_int_098_store_backend_selection(monkeypatch) -> None:
    from rag import retriever

    monkeypatch.setattr(retriever.settings, "VECTOR_BACKEND", "pgvector")
    assert retriever._store().__name__.endswith("pgvector_store")
    monkeypatch.setattr(retriever.settings, "VECTOR_BACKEND", "qdrant")
    assert retriever._store().__name__.endswith("qdrant_store")
