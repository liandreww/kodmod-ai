"""
KODMOD AI — Qdrant Store (alternative vector backend)
=====================================================

Drop-in replacement for `pgvector_store` when `settings.VECTOR_BACKEND ==
"qdrant"`. Use this in deployments where you want to scale RAG independently
of the OLTP Postgres (e.g. a managed Qdrant cluster).

Same API surface: `upsert_chunks`, `query`, `delete_by_source`.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_COLLECTION = "kodmod_curriculum"


@lru_cache(maxsize=1)
def _client():
    from qdrant_client import QdrantClient  # type: ignore

    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    _ensure_collection(client)
    return client


def _ensure_collection(client) -> None:
    from qdrant_client.http.models import Distance, VectorParams  # type: ignore

    existing = {c.name for c in client.get_collections().collections}
    if _COLLECTION not in existing:
        client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection %s", _COLLECTION)


async def upsert_chunks(records: list[dict]) -> int:
    if not records:
        return 0
    from qdrant_client.http.models import PointStruct  # type: ignore

    points = [
        PointStruct(
            id=r.get("id") or str(uuid.uuid4()),
            vector=r["embedding"],
            payload={
                "text": r["text"],
                "source": r.get("source", ""),
                "language": r.get("language", "id"),
                "concept_id": str(r.get("concept_id")) if r.get("concept_id") else None,
                "section_title": r.get("section_title"),
                "chunk_index": r.get("chunk_index", 0),
                "accessibility_metadata": r.get("accessibility_metadata", {}),
            },
        )
        for r in records
    ]
    _client().upsert(collection_name=_COLLECTION, points=points, wait=False)
    logger.info("Upserted %d points into Qdrant", len(points))
    return len(points)


async def query(
    embedding: list[float],
    *,
    top_k: int = 8,
    concept_id: Optional[uuid.UUID] = None,
    language: Optional[str] = None,
) -> list[dict]:
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue  # type: ignore

    must = []
    if concept_id:
        must.append(FieldCondition(key="concept_id", match=MatchValue(value=str(concept_id))))
    if language:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))

    qfilter = Filter(must=must) if must else None
    hits = _client().search(
        collection_name=_COLLECTION,
        query_vector=embedding,
        limit=top_k,
        query_filter=qfilter,
    )
    return [
        {
            "id": str(h.id),
            "text": h.payload.get("text", ""),
            "source": h.payload.get("source"),
            "section_title": h.payload.get("section_title"),
            "accessibility_metadata": h.payload.get("accessibility_metadata", {}),
            "score": float(h.score),
        }
        for h in hits
    ]


async def delete_by_source(source: str) -> int:
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue  # type: ignore

    res = _client().delete(
        collection_name=_COLLECTION,
        points_selector=Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))]),
    )
    # Qdrant doesn't return a count; we return -1 to signal "unknown".
    return -1 if res else 0
