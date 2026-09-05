"""
KODMOD AI — Accessibility Agent
================================

The last node every speaking path runs through. Takes whatever
`generated_response` the upstream agents produced and rewrites it to be
comfortable to *listen* to, whether through a screen reader or the browser's
text-to-speech.

Transformations
---------------
1. **De-visualize** — strip "see the figure", "as shown above", "look at",
   "the diagram below", etc. Replace with descriptive narration.
2. **De-format** — remove markdown (`**bold**`, headers, bullets, asterisks)
   that a screen reader reads as "asterisk asterisk bold asterisk asterisk".
3. **Number normalization** — "Bab 3.2" → "Bab 3 titik 2", so it is not read
   as a date.
4. **Sentence shortening** — splits sentences > ~25 words.
5. **Simplification** — if `accessibility_flags["simplify_language"]` is set
   (e.g. for younger learners), invokes an LLM rewrite to grade-school level.

Note there is no pacing markup. Speech synthesis happens in the browser, so
anything this node emits is also *displayed*; SSML tags would leak onto the
screen as literal text.

The agent operates in two modes:
* **Fast path** — pure regex / rule-based, runs in < 5 ms. Used by default.
* **LLM path** — invoked only when fast-path heuristics flag risky output
  (lots of formatting, very long, or simplification requested).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from accessibility.narration import describe_visuals_in_text
from accessibility.simplifier import simplify_with_llm
from graphs.state import KODMODState

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
            "next_action": "respond",
            "last_node": "accessibility",
        }

    flags = state.get("accessibility_flags", {})
    profile = state.get("learning_profile", {}).get("accessibility", {})
    simplify = bool(flags.get("simplify_language") or profile.get("simplify_language"))

    # ---- Step 1: fast-path rule transforms ------------------------------
    cleaned = _strip_markdown(text)
    cleaned = _normalize_dashes(cleaned)
    cleaned = _replace_visual_refs(cleaned)
    cleaned = describe_visuals_in_text(cleaned)
    cleaned = _split_long_sentences(cleaned)
    cleaned = _normalize_numbers(cleaned)

    # ---- Step 2: optional LLM simplification ----------------------------
    if simplify or _should_simplify(cleaned):
        cleaned = await simplify_with_llm(
            cleaned,
            target_grade_level=str(profile.get("target_grade", 7)),
        )

    # A quiz-remediation explanation (scoring -> tutoring -> reflection) must
    # say the student is still mid-quiz, appended last so reflection's rewrite
    # can't drop it and no rewording can water it down.
    if (
        state.get("intent") == "quiz"
        and state.get("quiz_session_id")
        and state.get("last_node") in ("tutoring", "reflection")
    ):
        cleaned = cleaned.rstrip() + " Sekarang, coba jawab pertanyaan kuis tadi lagi."

    log.info(
        "Accessibility polish: %d -> %d chars (simplify=%s)", len(text), len(cleaned), simplify
    )

    return {
        "accessible_response": cleaned,
        "next_action": "respond",
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


def _normalize_dashes(text: str) -> str:
    """Turn typographic dashes into punctuation that reads and speaks cleanly.

    A screen reader announces an em-dash as a pause of unpredictable length, or
    sometimes as nothing at all, and the product style avoids them in any case.
    A dash used as a parenthetical or an aside becomes a comma.
    """
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    return re.sub(r",\s*,", ",", text)


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
            return f"{sentence[:idx]}.{sentence[idx + 1 :]}{terminator} "
        return match.group(0)

    return _LONG_SENTENCE.sub(splitter, text)


def _normalize_numbers(text: str) -> str:
    """
    Light normalization. Heavy lifting (e.g. 1.234.567 → 'satu juta dua ratus...')
    happens in the speech engine; here we just make decimals readable.
    """
    # "Bab 3.2" → "Bab 3 titik 2" so it is not read as a date
    text = re.sub(r"\b(\d+)\.(\d+)\b", r"\1 titik \2", text)
    return text


def _should_simplify(text: str) -> bool:
    """Heuristic — invoke LLM simplifier for very long or jargon-heavy output."""
    return len(text) > 1200 or text.count(",") > 30
