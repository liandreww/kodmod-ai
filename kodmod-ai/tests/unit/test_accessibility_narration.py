"""Unit tests for accessibility/narration.describe_visuals_in_text."""
from __future__ import annotations

import pytest

from accessibility.narration import describe_visuals_in_text


def test_replaces_lihat_gambar():
    text = "Seperti pada gambar 3.2, persamaan ini memiliki dua akar."
    out = describe_visuals_in_text(text)
    assert "gambar" not in out.lower() or "ilustrasi" in out.lower()


def test_replaces_color_reference():
    text = "Garis berwarna merah menunjukkan tren turun."
    out = describe_visuals_in_text(text)
    assert "merah" not in out.lower()


def test_idempotent():
    text = "Penjelasan tanpa referensi visual sama sekali."
    assert describe_visuals_in_text(text) == text


def test_handles_empty_input():
    assert describe_visuals_in_text("") == ""
    assert describe_visuals_in_text(None) is None  # type: ignore[arg-type]


def test_collapses_whitespace_after_substitution():
    text = "Lihat tabel di atas    untuk angka."
    out = describe_visuals_in_text(text)
    assert "  " not in out


def test_substitutes_with_context_descriptions():
    text = "Lihat gambar 4.1 untuk skema sirkuit."
    ctx = {"gambar_4.1": "rangkaian listrik dengan baterai dan dua resistor"}
    out = describe_visuals_in_text(text, context_descriptions=ctx)
    # Either rewritten phrase or contextual description present.
    assert "rangkaian listrik" in out or "ilustrasi" in out.lower()
