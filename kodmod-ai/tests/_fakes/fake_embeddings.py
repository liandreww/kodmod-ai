"""Deterministic fake embeddings — hash-seeded unit vectors, no model download.

Signature matches ``rag.embeddings.embed_text``:
    async def embed_text(texts: Sequence[str]) -> list[list[float]]
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence

EMBED_DIM = int(os.getenv("EMBEDDING_DIM", os.getenv("KODMOD_EMBED_DIM", "1024")))


def _seeded_vector(text: str, dim: int = EMBED_DIM) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    out: list[float] = []
    block = h
    i = 0
    while len(out) < dim:
        out.append(((block[i % len(block)] / 255.0) * 2.0) - 1.0)
        i += 1
        if i % len(block) == 0:
            block = hashlib.sha256(block).digest()
    norm = sum(v * v for v in out) ** 0.5 or 1.0
    return [v / norm for v in out]


async def fake_embed_text(texts: Sequence[str]) -> list[list[float]]:
    if not texts:
        return []
    return [_seeded_vector(str(t)) for t in texts]


def fake_embed_text_sync(texts: Sequence[str]) -> list[list[float]]:
    if not texts:
        return []
    return [_seeded_vector(str(t)) for t in texts]
