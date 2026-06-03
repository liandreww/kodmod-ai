"""
KODMOD AI — Ingest Documents Script
===================================

Walks a directory and ingests every supported file into the RAG vector
store. Wraps `rag.ingestion.ingest_paths` with concept-level batching
and a progress bar.

Run:
    python scripts/ingest_documents.py --path data/curriculum/biology --concept-slug fotosintesis
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from database.models import Concept
from database.session import async_session, close_db, init_db
from rag.ingestion import ingest_paths

logger = logging.getLogger(__name__)


async def _resolve_concept_id(slug: str | None):
    if not slug:
        return None
    async with async_session() as session:
        c = (await session.execute(select(Concept).where(Concept.slug == slug))).scalar_one_or_none()
    if c is None:
        raise SystemExit(f"Concept slug {slug!r} not found. Run seed_curriculum.py first?")
    return c.id


async def _amain(args) -> None:
    await init_db()
    try:
        concept_id = await _resolve_concept_id(args.concept_slug)
        root = Path(args.path)
        if root.is_dir():
            files = [p for p in root.rglob("*") if p.suffix.lower() in {".md", ".txt", ".pdf"}]
        else:
            files = [root]
        if not files:
            logger.warning("No supported files found at %s", root)
            return
        n = await ingest_paths(files, concept_id=concept_id, language=args.language)
        logger.info("Ingested %d chunks from %d file(s)", n, len(files))
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="File or directory to ingest")
    parser.add_argument("--concept-slug", default=None, help="Optional concept slug to attach chunks to")
    parser.add_argument("--language", default="id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
