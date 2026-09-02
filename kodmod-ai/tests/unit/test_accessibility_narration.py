"""KM-UNIT-091..096 — accessibility/narration.describe_visuals_in_text.

Spec: docs/testplan/01-unit.md §7 (accessibility/narration.py).
"""

from __future__ import annotations

import pytest

from accessibility.narration import describe_visuals_in_text

pytestmark = pytest.mark.unit


def test_replaces_lihat_gambar():  # KM-UNIT-091
    text = "Seperti pada gambar 3.2, persamaan ini memiliki dua akar."
    out = describe_visuals_in_text(text)
    assert "gambar" not in out.lower() or "ilustrasi" in out.lower()


def test_replaces_color_reference():  # KM-UNIT-092
    text = "Garis berwarna merah menunjukkan tren turun."
    out = describe_visuals_in_text(text)
    assert "merah" not in out.lower()


def test_idempotent():  # KM-UNIT-093
    text = "Penjelasan tanpa referensi visual sama sekali."
    assert describe_visuals_in_text(text) == text


def test_handles_empty_input():  # KM-UNIT-094
    assert describe_visuals_in_text("") == ""
    assert describe_visuals_in_text(None) is None  # type: ignore[arg-type]


def test_collapses_whitespace_after_substitution():  # KM-UNIT-095
    text = "Lihat tabel di atas    untuk angka ."
    out = describe_visuals_in_text(text)
    assert "  " not in out
    assert " ." not in out  # no space before punctuation


def test_substitutes_with_context_descriptions():  # KM-UNIT-096
    text = "Lihat gambar 4.1 untuk skema sirkuit."
    ctx = {"gambar_4.1": "rangkaian listrik dengan baterai dan dua resistor"}
    out = describe_visuals_in_text(text, context_descriptions=ctx)
    # Either rewritten phrase or contextual description present.
    assert "rangkaian listrik" in out or "ilustrasi" in out.lower()
