"""KM-UNIT-080..090 — pure accessibility helpers (agents/accessibility_agent.py).

Oracle: the regex constants + helper functions, and the transform order in
`accessibility_node`. `describe_visuals_in_text` (narration.py) is covered in
test_accessibility_narration.py.

Spec: docs/testplan/01-unit.md §7.
"""

from __future__ import annotations

import pytest

from agents.accessibility_agent import (
    _add_ssml_breaks,
    _normalize_numbers,
    _replace_visual_refs,
    _should_simplify,
    _split_long_sentences,
    _strip_markdown,
    accessibility_node,
)

pytestmark = pytest.mark.unit


def test_strip_markdown() -> None:  # KM-UNIT-080
    out = _strip_markdown("**tebal** `kode` [x](u)\n# Judul")
    assert "**" not in out
    assert "`" not in out
    assert "#" not in out
    assert "[x](u)" not in out
    assert "x" in out and "Judul" in out


def test_replace_visual_refs_id() -> None:  # KM-UNIT-081
    out = _replace_visual_refs("lihat gambar di atas")
    assert "lihat gambar" not in out.lower()
    assert "perhatikan baik-baik" in out


def test_replace_visual_refs_en() -> None:  # KM-UNIT-082
    out = _replace_visual_refs("as shown in the figure below")
    assert "as shown" not in out.lower()
    assert "perhatikan baik-baik" in out


def test_split_long_sentence_breaks_at_comma() -> None:  # KM-UNIT-083
    long = "x" * 50 + ", " + "y" * 100  # comma sits at index 50 (> 40)
    out = _split_long_sentences(long + ". Akhir.")
    assert "," not in out
    assert "x" * 50 + "." in out


def test_split_long_sentence_without_comma_is_untouched() -> None:  # KM-UNIT-084
    text = "z" * 150 + ". Akhir."
    assert _split_long_sentences(text) == text


def test_normalize_numbers_spells_decimals() -> None:  # KM-UNIT-085
    out = _normalize_numbers("nilai 3.2 dan 10.75")
    assert "3 titik 2" in out
    assert "10 titik 75" in out


def test_add_ssml_breaks() -> None:  # KM-UNIT-086
    out = _add_ssml_breaks("Benar? Bagus! Lalu. Selanjutnya.")
    assert out.count("400ms") == 2  # break after ? and after !
    assert "250ms" in out  # shorter break after ". " before a capital


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a" * 1300, True),  # KM-UNIT-087 — length
        ("x, " * 31, True),  # KM-UNIT-088 — 31 commas, < 1200 chars
        ("kata, " * 5 + "a" * 170, False),  # KM-UNIT-089 — normal
    ],
)
def test_should_simplify(text: str, expected: bool) -> None:
    assert _should_simplify(text) is expected


async def test_pipeline_fast_path_order() -> None:  # KM-UNIT-090
    state = {
        "generated_response": (
            "**Penting**: lihat gambar 3.2 di atas. Apakah kamu paham? Mari lanjut."
        )
    }
    out = (await accessibility_node(state))["accessible_response"]
    assert "**" not in out  # markdown stripped
    assert "lihat gambar" not in out.lower()  # visual ref replaced
    assert "3 titik 2" in out  # numbers normalized
    assert "400ms" in out  # SSML pacing added last
