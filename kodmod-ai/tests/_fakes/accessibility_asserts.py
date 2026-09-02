"""Reusable assertions for the audio-only / accessibility contract.

Used by Stage 4, 6 and 7. See docs/testplan/06-e2e.md (KM-E2E-010).
"""

from __future__ import annotations

import re

_VISUAL_PATTERNS = [
    r"lihat\s+(gambar|diagram|tabel|grafik|ilustrasi)",
    r"seperti\s+(terlihat|tampak|ditunjukkan)",
    r"\b(di\s+atas|di\s+bawah|di\s+samping)\b",
    r"see\s+(the\s+)?(figure|diagram|chart|table|image)",
    r"as\s+shown",
    r"as\s+you\s+can\s+see",
    r"look\s+at\b",
]
_MARKDOWN = re.compile(r"(\*\*|__|`|^#{1,6}\s|^\s*[-*]\s)", re.MULTILINE)
_RAW_DECIMAL = re.compile(r"\d+\.\d+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def assert_no_visual_refs(text: str) -> None:
    low = text.lower()
    hits = [p for p in _VISUAL_PATTERNS if re.search(p, low)]
    assert not hits, f"visual references leaked into spoken text: {hits}\n{text!r}"


def assert_no_markdown(text: str) -> None:
    m = _MARKDOWN.search(text)
    assert not m, f"markdown leaked into spoken text: {m.group(0)!r}\n{text!r}"


def assert_numbers_spelled(text: str) -> None:
    m = _RAW_DECIMAL.search(text)
    assert not m, f"raw decimal not spelled out: {m.group(0)!r}\n{text!r}"


def assert_short_sentences(text: str, max_words: int = 22) -> None:
    for s in _SENTENCE_SPLIT.split(text.strip()):
        s = s.strip()
        if not s:
            continue
        n = len(s.split())
        assert n <= max_words, f"sentence too long ({n} > {max_words} words): {s!r}"


def assert_accessible(text: str, *, max_words: int = 22) -> None:
    assert text and text.strip(), "empty spoken text"
    assert_no_visual_refs(text)
    assert_no_markdown(text)
    assert_numbers_spelled(text)
    assert_short_sentences(text, max_words=max_words)
