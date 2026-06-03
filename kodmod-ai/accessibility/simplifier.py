"""
KODMOD AI — LLM-Powered Accessibility Simplifier
================================================

Takes a piece of generated text (typically a tutoring explanation) and
rewrites it for a blind / low-vision listener:

- Removes visual references ("seperti pada gambar", "lihat tabel di atas")
- Splits long sentences (> MAX_SPOKEN_SENTENCE_WORDS)
- Replaces dense jargon with plain Bahasa Indonesia
- Preserves pedagogical content — it is *not* allowed to drop key facts.

This is the "second pass" used selectively by `accessibility_agent`. The
fast regex-only path covers most cases; only when the response is long or
flagged as visually-dependent do we invoke this LLM-backed simplifier.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from tools.llm_client import get_quiz_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Anda adalah ahli aksesibilitas pendidikan untuk siswa tunanetra.
Tugas Anda: menulis ulang teks tutor agar nyaman didengarkan menggunakan TTS.

ATURAN MUTLAK:
1. JANGAN menggunakan referensi visual ("seperti gambar", "lihat di atas",
   "perhatikan diagram", "garis berwarna merah", dst).
2. JANGAN menghilangkan fakta atau langkah penting dari penjelasan asli.
3. Pisahkan kalimat panjang menjadi kalimat pendek (maksimum 22 kata per kalimat).
4. Gunakan Bahasa Indonesia yang sederhana, ramah, dan ringkas.
5. Untuk angka dan rumus, eja dengan jelas (misal "3,14" -> "tiga koma satu empat").
6. Pertahankan urutan logis: definisi -> contoh -> penegasan.
7. JANGAN menambahkan informasi baru yang tidak ada di teks asli.
8. JANGAN menggunakan markdown atau format teks.

Output: hanya teks yang sudah disederhanakan, tanpa pembukaan atau komentar.
"""


async def simplify_with_llm(
    text: str,
    *,
    language: str = "id",
    max_sentence_words: int = 22,
    target_grade_level: Optional[str] = None,
) -> str:
    """
    Returns a simplified, audio-friendly version of `text`.
    Falls back to the original text on error to avoid breaking the pipeline.
    """
    if not text or len(text.split()) < 12:
        return text

    llm = get_quiz_llm(temperature=0.2)
    system = _SYSTEM_PROMPT
    if language == "en":
        system = system.replace("Bahasa Indonesia yang sederhana", "simple English")

    user_prompt = (
        f"Maksimum kata per kalimat: {max_sentence_words}.\n"
        + (f"Sesuaikan untuk siswa tingkat: {target_grade_level}.\n" if target_grade_level else "")
        + "\nTeks asli:\n---\n"
        + text
        + "\n---\n\nTeks setelah disederhanakan:"
    )

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user_prompt),
        ])
        out = (resp.content or "").strip() if hasattr(resp, "content") else str(resp).strip()
        return out or text
    except Exception as exc:  # pragma: no cover
        logger.warning("simplify_with_llm failed, returning original: %s", exc)
        return text
