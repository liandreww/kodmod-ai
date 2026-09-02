"""Stage 3 §7 — rag/stores/pgvector_store.py against real pgvector.

Spec: docs/testplan/03-integration.md §7 (KM-INT-080..088).
Embeddings are the deterministic hash-seeded 1024-d stub.
"""

from __future__ import annotations

import uuid

import pytest

from tests._fakes.fake_embeddings import fake_embed_text_sync

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.asyncio(loop_scope="session")]

CID_A = str(uuid.UUID("44444444-4444-4444-4444-44444444aaaa"))
CID_B = str(uuid.UUID("44444444-4444-4444-4444-44444444bbbb"))


def _rec(
    text: str, *, cid: str | None = None, language: str = "id", src: str = "s.md", idx: int = 0
):
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


async def _count(clause: str = "", params: dict | None = None) -> int:
    from sqlalchemy import text as sa_text

    from database.session import async_session

    async with async_session() as s:
        return (
            await s.execute(
                sa_text(f"SELECT count(*) FROM curriculum_chunks {clause}"), params or {}
            )
        ).scalar_one()


async def test_km_int_080_upsert_inserts(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores import pgvector_store as store

    recs = [_rec(f"pecahan bagian {i}", cid=CID_A, idx=i) for i in range(5)]
    n = await store.upsert_chunks(recs)
    assert n == 5
    assert await _count() == 5


async def test_km_int_081_upsert_conflict_updates(clean_db) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text as sa_text

    from database.session import async_session
    from rag.stores import pgvector_store as store

    recs = [_rec(f"awal {i}", cid=CID_A, idx=i) for i in range(5)]
    await store.upsert_chunks(recs)
    recs[0]["text"] = "konten diperbarui"
    recs[0]["embedding"] = fake_embed_text_sync(["konten diperbarui"])[0]
    await store.upsert_chunks(recs)

    assert await _count() == 5
    async with async_session() as s:
        content = (
            await s.execute(
                sa_text("SELECT content FROM curriculum_chunks WHERE id=:id"), {"id": recs[0]["id"]}
            )
        ).scalar_one()
    assert content == "konten diperbarui"


async def test_km_int_082_query_cosine_ranks_nearest_first(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores import pgvector_store as store

    texts = ["pecahan senilai", "penjumlahan pecahan", "tata surya planet"]
    recs = [_rec(t, cid=CID_A, idx=i) for i, t in enumerate(texts)]
    await store.upsert_chunks(recs)

    q = fake_embed_text_sync(["pecahan senilai"])[0]
    res = await store.query(q, top_k=3, language="id")
    assert res[0]["text"] == "pecahan senilai"
    assert res[0]["score"] >= res[-1]["score"]
    assert res[0]["score"] == pytest.approx(1.0, abs=1e-4)  # identical vector -> distance 0


async def test_km_int_083_query_filters_concept_id(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores import pgvector_store as store

    await store.upsert_chunks(
        [_rec("A satu", cid=CID_A), _rec("A dua", cid=CID_A), _rec("B satu", cid=CID_B)]
    )
    res = await store.query(
        fake_embed_text_sync(["apa saja"])[0], top_k=10, concept_id=uuid.UUID(CID_A), language="id"
    )
    assert res and all(r["text"].startswith("A ") for r in res)


async def test_km_int_084_query_filters_language(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores import pgvector_store as store

    await store.upsert_chunks(
        [_rec("bahasa id", language="id"), _rec("english text", language="en")]
    )
    res = await store.query(fake_embed_text_sync(["x"])[0], top_k=10, language="en")
    assert [r["text"] for r in res] == ["english text"]


async def test_km_int_085_query_top_k_limit(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores import pgvector_store as store

    await store.upsert_chunks([_rec(f"chunk {i}", idx=i) for i in range(6)])
    res = await store.query(fake_embed_text_sync(["chunk 0"])[0], top_k=3, language="id")
    assert len(res) == 3
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)


async def test_km_int_086_pgvectorstore_similarity_search_parses_uuid(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores.pgvector_store import PgVectorStore

    await PgVectorStore().upsert_chunks([_rec("A", cid=CID_A), _rec("B", cid=CID_B)])
    res = await PgVectorStore().similarity_search(
        embedding=fake_embed_text_sync(["x"])[0], top_k=10, filters={"concept_id": CID_A}
    )
    assert res and all(r["text"] == "A" for r in res)


async def test_km_int_087_delete_by_source(clean_db) -> None:  # type: ignore[no-untyped-def]
    from rag.stores import pgvector_store as store

    await store.upsert_chunks(
        [_rec("keep", src="keep.md"), _rec("drop 1", src="drop.md"), _rec("drop 2", src="drop.md")]
    )
    deleted = await store.delete_by_source("drop.md")
    assert deleted == 2
    assert await _count() == 1


async def test_km_int_088_query_plan_smoke(clean_db) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text as sa_text

    from database.session import async_session
    from rag.stores import pgvector_store as store
    from rag.stores.pgvector_store import _vec_literal

    await store.upsert_chunks([_rec(f"c {i}", idx=i) for i in range(5)])
    emb = _vec_literal(fake_embed_text_sync(["c 0"])[0])
    async with async_session() as s:
        plan = "\n".join(
            (
                await s.execute(
                    sa_text(
                        "EXPLAIN SELECT id FROM curriculum_chunks "
                        "ORDER BY embedding <=> CAST(:e AS vector) LIMIT 5"
                    ),
                    {"e": emb},
                )
            )
            .scalars()
            .all()
        )
    # tiny dataset: planner may pick a seq scan — just prove the query planned OK
    assert "curriculum_chunks" in plan
