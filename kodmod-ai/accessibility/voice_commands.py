"""
KODMOD AI — Voice Command Recognition
=====================================

Detects fixed-vocabulary navigation commands BEFORE we incur the cost of
running the full LangGraph router. These are the commands a blind user
needs to feel in control of pacing:

    "ulangi" / "repeat"        -> re-emit last assistant turn
    "berhenti" / "stop"        -> cancel current generation
    "lanjut" / "next"          -> advance to next item
    "kembali" / "back"         -> go back one item
    "bantuan" / "help"         -> read out available commands

Detection is regex-based for sub-millisecond latency. If no match, the
utterance is sent through to the intent router as normal.

Playback speed and volume are deliberately absent: speech synthesis runs in
the browser, so the client owns those controls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Keep these patterns conservative — false positives interrupt teaching.
_COMMANDS = {
    "repeat": re.compile(
        r"^\s*(ulangi(?:\s+lagi)?|repeat(?:\s+that)?|sekali\s+lagi|say\s+again)\s*[?.!]?\s*$", re.I
    ),
    "stop": re.compile(r"^\s*(berhenti|stop|cukup|udahan|hentikan)\s*[?.!]?\s*$", re.I),
    "next": re.compile(r"^\s*(lanjut(?:kan)?|berikutnya|next|continue)\s*[?.!]?\s*$", re.I),
    "back": re.compile(r"^\s*(kembali|sebelumnya|back|previous)\s*[?.!]?\s*$", re.I),
    "help": re.compile(r"^\s*(bantuan|tolong|help|menu)\s*[?.!]?\s*$", re.I),
    "start_quiz": re.compile(r"^\s*(mulai\s+kuis|start\s+quiz|kuis\s+sekarang)\s*[?.!]?\s*$", re.I),
}


@dataclass(frozen=True)
class VoiceCommand:
    name: str
    raw_text: str

    def is_terminal(self) -> bool:
        """Commands that should short-circuit the graph entirely."""
        return self.name in {"stop", "help", "repeat"}


def detect_command(text: str) -> VoiceCommand | None:
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
    "'lanjut' untuk melanjutkan, "
    "'mulai kuis' untuk memulai sesi kuis, "
    "atau 'berhenti' untuk menghentikan saya."
)

HELP_TEXT_EN = (
    "Available voice commands: "
    "say 'repeat' to hear the last explanation again, "
    "'next' to move on, "
    "'start quiz' to begin a quiz session, "
    "or 'stop' to interrupt me."
)


def help_text(language: str = "id") -> str:
    return HELP_TEXT_ID if language == "id" else HELP_TEXT_EN
