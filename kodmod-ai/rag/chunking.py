"""
KODMOD AI — Document Chunking
=============================

Splits source documents into RAG-ready chunks that respect:
- Section boundaries (headings)
- Sentence boundaries
- A target token budget
- Accessibility metadata (which figures/tables a chunk references)

The default strategy is a semantic-aware sliding window: hard split on
heading transitions, soft split on sentence boundaries within sections.

For curriculum content authored in markdown, we prefer to keep each
"learning objective" as its own chunk so retrieval pulls a coherent
explanation, not a fragment.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Heading patterns: markdown + Bahasa Indonesia textbook conventions.
_HEADING_RE = re.compile(
    r"^(?:#{1,4}\s+|Bab\s+\d+(?:\.\d+)?\s*[:\-]?\s*|Bagian\s+\d+\s*[:\-]?\s*|Sub\s*Bab\s+\d+(?:\.\d+)?\s*[:\-]?\s*)(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_FIGURE_RE = re.compile(r"(?:gambar|figure|tabel|table|diagram)\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁ-ÚÀ-Ï])")


@dataclass
class Chunk:
    text: str
    source: str
    section_title: Optional[str] = None
    chunk_index: int = 0
    referenced_figures: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _approx_tokens(text: str) -> int:
    # Cheap proxy without tokenizer — chars/4 works well enough for budgeting.
    return max(1, len(text) // 4)


def _split_on_headings(text: str) -> list[tuple[Optional[str], str]]:
    """Returns list of (section_title, body)."""
    parts: list[tuple[Optional[str], str]] = []
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [(None, text.strip())]

    if matches[0].start() > 0:
        parts.append((None, text[: matches[0].start()].strip()))

    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        parts.append((title, body))

    return [(t, b) for t, b in parts if b]


def _split_sentences(text: str) -> list[str]:
    sents = _SENTENCE_END.split(text)
    return [s.strip() for s in sents if s.strip()]


def chunk_document(
    text: str,
    *,
    source: str,
    target_tokens: int = 350,
    max_tokens: int = 500,
    overlap_sentences: int = 1,
) -> list[Chunk]:
    """
    Split `text` into chunks of ~target_tokens (max max_tokens), preserving
    section context. Adds an overlap of `overlap_sentences` sentences between
    consecutive chunks within a section so retrieval doesn't cut explanations.
    """
    sections = _split_on_headings(text)
    chunks: list[Chunk] = []
    chunk_idx = 0

    for section_title, body in sections:
        sentences = _split_sentences(body)
        if not sentences:
            continue

        buf: list[str] = []
        buf_tokens = 0

        def flush(extra_sentences: list[str] | None = None) -> None:
            nonlocal buf, buf_tokens, chunk_idx
            if not buf and not extra_sentences:
                return
            full = " ".join(extra_sentences or [] + buf)
            chunks.append(
                Chunk(
                    text=full,
                    source=source,
                    section_title=section_title,
                    chunk_index=chunk_idx,
                    referenced_figures=sorted({m.group(0) for m in _FIGURE_RE.finditer(full)}),
                )
            )
            chunk_idx += 1

        for sent in sentences:
            tokens = _approx_tokens(sent)
            if buf_tokens + tokens > max_tokens and buf:
                # Emit current and seed next chunk with overlap.
                flush()
                buf = buf[-overlap_sentences:] if overlap_sentences else []
                buf_tokens = sum(_approx_tokens(s) for s in buf)
            buf.append(sent)
            buf_tokens += tokens
            if buf_tokens >= target_tokens:
                flush()
                buf = buf[-overlap_sentences:] if overlap_sentences else []
                buf_tokens = sum(_approx_tokens(s) for s in buf)

        if buf:
            flush()

    logger.info("Chunked %s into %d chunks", source, len(chunks))
    return chunks


def chunks_to_payloads(chunks: Iterable[Chunk]) -> list[dict]:
    """Convert to the dict shape expected by the vector store ingestion."""
    return [
        {
            "text": c.text,
            "source": c.source,
            "section_title": c.section_title,
            "chunk_index": c.chunk_index,
            "referenced_figures": c.referenced_figures,
            "metadata": c.metadata,
        }
        for c in chunks
    ]
