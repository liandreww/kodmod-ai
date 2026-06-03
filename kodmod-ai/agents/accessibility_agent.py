"""
KODMOD AI — Accessibility Agent
================================

The final content gate before TTS synthesis. Takes whatever
`generated_response` the upstream agents produced and rewrites it for
accessible audio playback.

Transformations
---------------
1. **De-visualize** — strip "see the figure", "as shown above", "look at",
   "the diagram below", etc. Replace with descriptive narration.
2. **De-format** — remove markdown (`**bold**`, headers, bullets, asterisks)
   that TTS engines read as "asterisk asterisk bold asterisk asterisk".
3. **Number normalization** — "Bab 3.2" → "Bab tiga titik dua"; large
   numbers handled carefully so screen-readers and TTS speak them naturally.
4. **Sentence shortening** — splits sentences > ~25 words.
5. **Pacing markup** — inserts SSML-style pauses for the TTS engine where
   appropriate (after questions, before key terms).
6. **Simplification** — if `accessibility_flags["simplify_language"]` is set
   (e.g. for younger learners), invokes an LLM rewrite to grade-school level.

The agent operates in two modes:
* **Fast path** — pure regex / rule-based, runs in < 5 ms. Used by default.
* **LLM path** — invoked only when fast-path heuristics flag risky output
  (lots of formatting, very long, or simplification requested).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from graphs.state import KODMODState
from accessibility.simplifier import simplify_with_llm
from accessibility.narration import describe_visuals_in_text

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------

_VISUAL_REFS = re.compile(
    r"\b("
    r"lihat (gambar|diagram|tabel|grafik)|"
    r"seperti (terlihat|tampak|ditunjukkan)|"
    r"see (the )?(figure|diagram|chart|table|image)|"
    r"as shown|as you can see|look at|"
    r"di (atas|bawah|samping)"
    r")\b",
    flags=re.IGNORECASE,
)

_MARKDOWN = re.compile(r"(\*\*|__|`{1,3}|^#+\s*|^\s*[-*+]\s+)", flags=re.MULTILINE)

_LONG_SENTENCE = re.compile(r"([^.!?]{120,}?)([.!?])\s+")


async def accessibility_node(state: KODMODState) -> dict[str, Any]:
    """LangGraph node — polishes generated_response for audio output."""
    text = state.get("generated_response", "") or ""
    if not text.strip():
        return {
            "accessible_response": "",
            "next_action": "speak",
            "last_node": "accessibility",
        }

    flags = state.get("accessibility_flags", {})
    profile = state.get("learning_profile", {}).get("accessibility", {})
    simplify = bool(flags.get("simplify_language") or profile.get("simplify_language"))

    # ---- Step 1: fast-path rule transforms ------------------------------
    cleaned = _strip_markdown(text)
    cleaned = _replace_visual_refs(cleaned)
    cleaned = describe_visuals_in_text(cleaned)
    cleaned = _split_long_sentences(cleaned)
    cleaned = _normalize_numbers(cleaned)
    cleaned = _add_ssml_breaks(cleaned)

    # ---- Step 2: optional LLM simplification ----------------------------
    if simplify or _should_simplify(cleaned):
        cleaned = await simplify_with_llm(
            cleaned,
            target_grade=int(profile.get("target_grade", 7)),
        )

    log.info("Accessibility polish: %d → %d chars (simplify=%s)",
             len(text), len(cleaned), simplify)

    return {
        "accessible_response": cleaned,
        "next_action": "speak",
        "last_node": "accessibility",
    }


# ---------------------------------------------------------------------------
# Pure transformations
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # links → just label
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _replace_visual_refs(text: str) -> str:
    """Replace 'look at the chart' → 'consider the following'."""
    return _VISUAL_REFS.sub("perhatikan baik-baik", text)


def _split_long_sentences(text: str) -> str:
    """Insert breaks in sentences over ~120 chars at the nearest comma."""
    def splitter(match: re.Match) -> str:
        sentence = match.group(1)
        terminator = match.group(2)
        # Try to break at the last comma in the first 120 chars
        head = sentence[:120]
        idx = head.rfind(",")
        if idx > 40:
            return f"{sentence[:idx]}.{sentence[idx+1:]}{terminator} "
        return match.group(0)
    return _LONG_SENTENCE.sub(splitter, text)


def _normalize_numbers(text: str) -> str:
    """
    Light normalization. Heavy lifting (e.g. 1.234.567 → 'satu juta dua ratus...')
    happens in the TTS engine; here we just make decimals readable.
    """
    # "Bab 3.2" → "Bab 3 titik 2" so TTS doesn't read it as a date
    text = re.sub(r"\b(\d+)\.(\d+)\b", r"\1 titik \2", text)
    return text


def _add_ssml_breaks(text: str) -> str:
    """
    Add lightweight SSML-like markers. The TTS layer converts these to its
    engine-specific syntax (Piper, Azure, ElevenLabs all support breaks).
    """
    text = re.sub(r"([?!])\s+", r"\1 <break time=\"400ms\"/> ", text)
    text = re.sub(r"(\.) (?=[A-ZÄÜÖ])", r".<break time=\"250ms\"/> ", text)
    return text


def _should_simplify(text: str) -> bool:
    """Heuristic — invoke LLM simplifier for very long or jargon-heavy output."""
    return len(text) > 1200 or text.count(",") > 30
