"""
KODMOD AI — Visual Narration Helpers
====================================

When source content contains diagrams, tables, or charts, this module
generates *spoken-friendly* descriptions so a blind learner gets the same
informational payload as a sighted one.

Two paths:

1. `describe_visuals_in_text(text)`  — regex-based deterministic rewriter:
   replaces patterns like "lihat gambar 3.1", "tabel di atas", "seperti
   pada diagram" with informative substitutes pulled from local context.

2. `describe_image(image_bytes)`     — multimodal vision call (LLM with
   vision) that produces a structured Bahasa Indonesia narration.
   Used by the ingestion pipeline when chunking PDFs/lessons that contain
   embedded figures.

The deterministic path is what the live tutoring loop uses — it must not
add latency. The vision path runs offline at ingestion time so the
description is already cached in the RAG chunk metadata.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from tools.llm_client import get_tutor_llm

logger = logging.getLogger(__name__)

# Indonesian + English visual reference patterns.
_VISUAL_PATTERNS = [
    (re.compile(r"\b(?:seperti |lihat )?(?:pada )?gambar(?:\s+\d+(?:\.\d+)?)?\b", re.I),
     "berdasarkan ilustrasi yang dijelaskan"),
    (re.compile(r"\b(?:lihat|perhatikan)\s+(?:tabel|diagram|grafik|bagan)(?:\s+\w+)?\b", re.I),
     "perhatikan penjelasan berikut"),
    (re.compile(r"\b(?:see|refer to)\s+(?:figure|image|diagram|chart|table)\s*\d*\.?\d*\b", re.I),
     "based on the described illustration"),
    (re.compile(r"\b(?:di|pada)\s+(?:gambar|tabel|diagram)\s+(?:di\s+)?(?:atas|bawah|samping)\b", re.I),
     "berdasarkan penjelasan sebelumnya"),
    (re.compile(r"\bgaris\s+(?:berwarna\s+)?(?:merah|biru|hijau|kuning|hitam)\b", re.I),
     "garis penanda"),
    (re.compile(r"\barea\s+(?:berwarna|berarsir)\s+\w+\b", re.I),
     "area yang ditandai"),
]

_VISUAL_FALLBACK = re.compile(
    r"\b(?:figure|gambar|tabel|diagram|grafik|chart|bagan)\b\s*\d*\.?\d*",
    re.I,
)


def describe_visuals_in_text(
    text: str,
    *,
    context_descriptions: Optional[dict[str, str]] = None,
) -> str:
    """
    Replace visual references with audio-friendly substitutes.
    `context_descriptions` is an optional dict mapping figure id -> spoken
    description, populated from the RAG chunk's `accessibility_metadata`.

    Idempotent and side-effect free.
    """
    if not text:
        return text

    out = text
    # 1. Apply pattern-based rewrites
    for pattern, replacement in _VISUAL_PATTERNS:
        out = pattern.sub(replacement, out)

    # 2. Substitute known figure references with their stored descriptions.
    if context_descriptions:
        def _replace(m: re.Match) -> str:
            key = m.group(0).lower().replace(" ", "_")
            for fig_id, desc in context_descriptions.items():
                if fig_id.lower() in key:
                    return f"({desc})"
            return m.group(0)

        out = _VISUAL_FALLBACK.sub(_replace, out)

    # 3. Collapse whitespace artifacts.
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out


_VISION_SYSTEM = """Anda adalah pakar aksesibilitas yang membuat narasi suara
untuk siswa tunanetra. Berikan deskripsi yang ringkas, jelas, dan informatif
tentang gambar berikut. Fokus pada informasi pendidikan, bukan estetika.

ATURAN:
- 2 sampai 4 kalimat.
- Bahasa Indonesia sederhana.
- Jelaskan struktur (kiri/kanan, atas/bawah) dengan kata "bagian".
- Sebutkan label, angka, atau teks yang muncul di gambar.
- JANGAN katakan "saya melihat" atau "gambar ini menunjukkan" — langsung deskripsikan.
"""


async def describe_image(
    image_bytes: bytes,
    *,
    mime_type: str = "image/png",
    extra_context: Optional[str] = None,
) -> str:
    """
    Multimodal vision narration. Uses the tutor LLM (Claude/GPT-4) which
    supports vision. Returns Bahasa Indonesia spoken-friendly description.
    """
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        llm = get_tutor_llm(temperature=0.2)
        user_content = [
            {"type": "text", "text": (extra_context or "Deskripsikan gambar ini untuk siswa tunanetra.")},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{b64}"},
            },
        ]
        resp = await llm.ainvoke([
            SystemMessage(content=_VISION_SYSTEM),
            HumanMessage(content=user_content),
        ])
        text = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(text, list):
            # some providers return list-of-dicts
            text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
        return (text or "").strip()
    except Exception as exc:  # pragma: no cover
        logger.warning("describe_image failed: %s", exc)
        return "Gambar tidak dapat dideskripsikan otomatis."
