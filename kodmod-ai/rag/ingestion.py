"""
KODMOD AI — RAG Ingestion Pipeline
==================================

Reads source documents, chunks them, embeds, attaches accessibility
metadata (figure descriptions), and persists to the configured vector
store.

Supported sources (via plugins):
- Markdown files (.md)
- Plain text (.txt)
- PDF (via pypdf — text-only; figures are described separately)
- Lesson rows from the relational DB

Run from CLI:

    python -m rag.ingestion --path data/curriculum/ --concept biology
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Iterable, Optional

from rag.chunking import chunk_document, chunks_to_payloads
from rag.embeddings import embed_text

logger = logging.getLogger(__name__)


def _load_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(str(path))
            return "\n\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            logger.warning("pypdf not installed; skipping %s", path)
            return ""
    return path.read_text(encoding="utf-8")


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    # embeddings.embed_text already supports batched calls in providers,
    # but we sequentialise here for simplicity. For large ingestions,
    # swap this for a true batch method on the embedder.
    return [await embed_text(t) for t in texts]


async def ingest_paths(
    paths: Iterable[Path],
    *,
    concept_id: Optional[uuid.UUID] = None,
    language: str = "id",
    target_tokens: int = 350,
) -> int:
    """Ingest one or more files; returns number of chunks written."""
    if settings_backend := __import__("config.settings", fromlist=["settings"]).settings:
        if settings_backend.VECTOR_BACKEND == "qdrant":
            from rag.stores import qdrant_store as store
        else:
            from rag.stores import pgvector_store as store
    else:  # pragma: no cover
        from rag.stores import pgvector_store as store

    total = 0
    for path in paths:
        path = Path(path)
        if not path.exists():
            logger.warning("Path %s missing — skipping", path)
            continue
        text = _load_text(path)
        if not text.strip():
            continue
        chunks = chunk_document(text, source=str(path), target_tokens=target_tokens)
        payloads = chunks_to_payloads(chunks)

        embeddings = await _embed_batch([p["text"] for p in payloads])
        records = []
        for p, emb in zip(payloads, embeddings):
            records.append({
                "id": str(uuid.uuid4()),
                "text": p["text"],
                "embedding": emb,
                "source": p["source"],
                "language": language,
                "concept_id": concept_id,
                "chunk_index": p["chunk_index"],
                "section_title": p.get("section_title"),
                "accessibility_metadata": {
                    "referenced_figures": p.get("referenced_figures", []),
                    **p.get("metadata", {}),
                },
            })
        n = await store.upsert_chunks(records)
        total += n
        logger.info("Ingested %s -> %d chunks", path, n)
    return total


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Directory or file to ingest")
    parser.add_argument("--concept-id", default=None)
    parser.add_argument("--language", default="id")
    args = parser.parse_args()

    root = Path(args.path)
    if root.is_dir():
        files = [p for p in root.rglob("*") if p.suffix.lower() in {".md", ".txt", ".pdf"}]
    else:
        files = [root]

    concept_id = uuid.UUID(args.concept_id) if args.concept_id else None
    n = asyncio.run(ingest_paths(files, concept_id=concept_id, language=args.language))
    print(f"Ingested {n} chunks from {len(files)} file(s)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli()
