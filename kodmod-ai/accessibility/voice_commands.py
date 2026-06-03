"""
KODMOD AI — Voice Command Recognition
=====================================

Detects fixed-vocabulary navigation commands BEFORE we incur the cost of
running the full LangGraph router. These are the commands a blind user
needs to feel in control of pacing:

    "ulangi" / "repeat"        -> re-emit last assistant turn
    "lebih pelan" / "slower"   -> reduce TTS rate
    "lebih cepat" / "faster"   -> increase TTS rate
    "berhenti" / "stop"        -> cancel current generation
    "lanjut" / "next"          -> advance to next item
    "kembali" / "back"         -> go back one item
    "bantuan" / "help"         -> read out available commands

Detection is regex-based for sub-millisecond latency. If no match, the
utterance is sent through to the intent router as normal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Keep these patterns conservative — false positives interrupt teaching.
_COMMANDS = {
    "repeat":     re.compile(r"^\s*(ulangi(?:\s+lagi)?|repeat(?:\s+that)?|sekali\s+lagi|say\s+again)\s*[?.!]?\s*$", re.I),
    "stop":       re.compile(r"^\s*(berhenti|stop|cukup|udahan|hentikan)\s*[?.!]?\s*$", re.I),
    "slower":     re.compile(r"^\s*(lebih\s+)?(pelan|lambat|slower|slow\s+down)(\s+lagi)?\s*[?.!]?\s*$", re.I),
    "faster":     re.compile(r"^\s*(lebih\s+)?(cepat|kencang|faster|speed\s+up)(\s+lagi)?\s*[?.!]?\s*$", re.I),
    "next":       re.compile(r"^\s*(lanjut(?:kan)?|berikutnya|next|continue)\s*[?.!]?\s*$", re.I),
    "back":       re.compile(r"^\s*(kembali|sebelumnya|back|previous)\s*[?.!]?\s*$", re.I),
    "help":       re.compile(r"^\s*(bantuan|tolong|help|menu)\s*[?.!]?\s*$", re.I),
    "louder":     re.compile(r"^\s*(lebih\s+)?(keras|nyaring|louder)\s*[?.!]?\s*$", re.I),
    "quieter":    re.compile(r"^\s*(lebih\s+)?(pelan\s+suara|quieter|softer)\s*[?.!]?\s*$", re.I),
    "start_quiz": re.compile(r"^\s*(mulai\s+kuis|start\s+quiz|kuis\s+sekarang)\s*[?.!]?\s*$", re.I),
}


@dataclass(frozen=True)
class VoiceCommand:
    name: str
    raw_text: str

    def is_terminal(self) -> bool:
        """Commands that should short-circuit the graph entirely."""
        return self.name in {"stop", "help", "repeat"}


def detect_command(text: str) -> Optional[VoiceCommand]:
    """Return a VoiceCommand if `text` matches a fixed command, else None."""
    if not text:
        return None
    norm = text.strip().lower()
    for name, pattern in _COMMANDS.items():
        if pattern.match(norm):
            return VoiceCommand(name=name, raw_text=text)
    return None


HELP_TEXT_ID = (
    "Beberapa perintah suara yang tersedia: "
    "ucapkan 'ulangi' untuk mengulang penjelasan, "
    "'lebih pelan' atau 'lebih cepat' untuk mengubah kecepatan suara, "
    "'lanjut' untuk melanjutkan, "
    "'mulai kuis' untuk memulai sesi kuis, "
    "atau 'berhenti' untuk menghentikan saya."
)

HELP_TEXT_EN = (
    "Available voice commands: "
    "say 'repeat' to hear the last explanation again, "
    "'slower' or 'faster' to change my speaking speed, "
    "'next' to move on, "
    "'start quiz' to begin a quiz session, "
    "or 'stop' to interrupt me."
)


def help_text(language: str = "id") -> str:
    return HELP_TEXT_ID if language == "id" else HELP_TEXT_EN
