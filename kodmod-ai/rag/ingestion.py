"""
KODMOD AI — RAG Ingestion Pipeline
==================================

Reads source documents, chunks them, embeds, attaches accessibility
metadata (figure descriptions), and persists to pgvector.

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
from collections.abc import Iterable
from pathlib import Path

from rag.chunking import chunk_document, chunks_to_payloads
from rag.embeddings import embed_text
from rag.stores import pgvector_store

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
    # embed_text takes a *sequence* of strings and returns one vector per
    # string. Passing a bare str here would embed it character-by-character.
    if not texts:
        return []
    return await embed_text(texts)


async def ingest_paths(
    paths: Iterable[Path],
    *,
    concept_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    language: str = "id",
    target_tokens: int = 350,
) -> int:
    """Ingest one or more files; returns number of chunks written.

    ``subject_id`` scopes the chunks so a student's question only searches the
    subject they picked; ``document_id`` ties them back to the upload row so
    deleting a document can delete its chunks.
    """
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
        for p, emb in zip(payloads, embeddings, strict=False):
            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": p["text"],
                    "embedding": emb,
                    "source": p["source"],
                    "language": language,
                    "concept_id": concept_id,
                    "subject_id": subject_id,
                    "document_id": document_id,
                    "chunk_index": p["chunk_index"],
                    "section_title": p.get("section_title"),
                    "accessibility_metadata": {
                        "referenced_figures": p.get("referenced_figures", []),
                        **p.get("metadata", {}),
                    },
                }
            )
        n = await pgvector_store.upsert_chunks(records)
        total += n
        logger.info("Ingested %s -> %d chunks", path, n)
    return total


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Directory or file to ingest")
    parser.add_argument("--concept-id", default=None)
    parser.add_argument("--subject-id", default=None)
    parser.add_argument("--language", default="id")
    args = parser.parse_args()

    root = Path(args.path)
    if root.is_dir():
        files = [p for p in root.rglob("*") if p.suffix.lower() in {".md", ".txt", ".pdf"}]
    else:
        files = [root]

    concept_id = uuid.UUID(args.concept_id) if args.concept_id else None
    subject_id = uuid.UUID(args.subject_id) if args.subject_id else None
    n = asyncio.run(
        ingest_paths(files, concept_id=concept_id, subject_id=subject_id, language=args.language)
    )
    print(f"Ingested {n} chunks from {len(files)} file(s)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli()
