"""Unit tests for accessibility/voice_commands.detect_command."""
from __future__ import annotations

import pytest

from accessibility.voice_commands import VoiceCommand, detect_command, help_text


@pytest.mark.parametrize(
    "utterance,expected_name",
    [
        ("ulangi", "repeat"),
        ("ulangi lagi", "repeat"),
        ("repeat that", "repeat"),
        ("berhenti", "stop"),
        ("STOP", "stop"),
        ("lebih pelan", "slower"),
        ("slower", "slower"),
        ("lebih cepat", "faster"),
        ("lanjut", "next"),
        ("kembali", "back"),
        ("bantuan", "help"),
        ("mulai kuis", "start_quiz"),
        ("start quiz", "start_quiz"),
    ],
)
def test_detects_command(utterance, expected_name):
    cmd = detect_command(utterance)
    assert isinstance(cmd, VoiceCommand)
    assert cmd.name == expected_name


@pytest.mark.parametrize(
    "utterance",
    [
        "apa itu fotosintesis",
        "tolong jelaskan tata surya",
        "saya tidak mengerti",
        "",
    ],
)
def test_non_commands_return_none(utterance):
    assert detect_command(utterance) is None


def test_help_text_localised():
    assert "ulangi" in help_text("id")
    assert "repeat" in help_text("en")


def test_terminal_classification():
    assert detect_command("stop").is_terminal()
    assert detect_command("ulangi").is_terminal()
    assert not detect_command("lanjut").is_terminal()
