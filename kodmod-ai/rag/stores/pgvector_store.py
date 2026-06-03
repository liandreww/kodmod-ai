"""
KODMOD AI — pgvector Store
==========================

Backs the RAG retrieval against the `curriculum_chunks` table created in
`schema.sql` (with HNSW index on a 1024-d vector column).

Design choices:
- We hand-write SQL (asyncpg via SQLAlchemy connection) because pgvector
  ORM support isn't worth the dependency surface for two simple queries.
- All embeddings are normalised (BGE-M3 outputs are already unit-norm)
  so the operator `<=>` (cosine distance) is the right similarity metric.
- Filters: optional concept_id, source, language.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import text

from database.session import async_session

logger = logging.getLogger(__name__)


def _vec_literal(vec: list[float]) -> str:
    """Format a Python list as a pgvector literal."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


async def upsert_chunks(records: list[dict]) -> int:
    """
    Insert (or replace) chunk rows.
    Each record must have:
      id (str/uuid), text, embedding (list[float]), source, language,
      concept_id (uuid|None), chunk_index, accessibility_metadata (dict)
    """
    if not records:
        return 0
    sql = text("""
        INSERT INTO curriculum_chunks
          (id, content, embedding, source, language, concept_id,
           chunk_index, section_title, accessibility_metadata, created_at)
        VALUES
          (:id, :content, CAST(:embedding AS vector), :source, :language, :concept_id,
           :chunk_index, :section_title, CAST(:meta AS jsonb), NOW())
        ON CONFLICT (id) DO UPDATE SET
          content = EXCLUDED.content,
          embedding = EXCLUDED.embedding,
          accessibility_metadata = EXCLUDED.accessibility_metadata;
    """)
    n = 0
    async with async_session() as session:
        for r in records:
            await session.execute(sql, {
                "id": r.get("id") or str(uuid.uuid4()),
                "content": r["text"],
                "embedding": _vec_literal(r["embedding"]),
                "source": r.get("source", ""),
                "language": r.get("language", "id"),
                "concept_id": r.get("concept_id"),
                "chunk_index": r.get("chunk_index", 0),
                "section_title": r.get("section_title"),
                "meta": __import__("json").dumps(r.get("accessibility_metadata", {})),
            })
            n += 1
    logger.info("Upserted %d chunks into curriculum_chunks", n)
    return n


async def query(
    embedding: list[float],
    *,
    top_k: int = 8,
    concept_id: Optional[uuid.UUID] = None,
    language: Optional[str] = None,
) -> list[dict]:
    """
    Cosine-similarity search.
    Returns dicts with: id, text, source, section_title, score,
    accessibility_metadata.
    """
    where_clauses = []
    params = {"emb": _vec_literal(embedding), "k": top_k}

    if concept_id:
        where_clauses.append("concept_id = :concept_id")
        params["concept_id"] = str(concept_id)
    if language:
        where_clauses.append("language = :language")
        params["language"] = language

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = text(f"""
        SELECT id::text AS id,
               content AS text,
               source,
               section_title,
               accessibility_metadata,
               1 - (embedding <=> CAST(:emb AS vector)) AS score
        FROM curriculum_chunks
        {where_sql}
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT :k;
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


async def delete_by_source(source: str) -> int:
    sql = text("DELETE FROM curriculum_chunks WHERE source = :source")
    async with async_session() as session:
        res = await session.execute(sql, {"source": source})
    return res.rowcount or 0
