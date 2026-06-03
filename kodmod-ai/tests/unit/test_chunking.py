"""Unit tests for rag/chunking."""
from __future__ import annotations

from rag.chunking import chunk_document


def test_simple_text_yields_at_least_one_chunk():
    text = "Ini kalimat pertama. Ini kalimat kedua. Dan kalimat ketiga."
    chunks = chunk_document(text, source="test.md")
    assert len(chunks) >= 1
    assert all(c.text.strip() for c in chunks)


def test_respects_section_boundaries():
    text = """# Bab 1: Pengantar
Kalimat dalam bab satu yang menjelaskan konsep.

## Bagian 1.1: Detail
Detail yang lebih dalam dan teknis.

# Bab 2: Lanjutan
Materi bab dua dengan penekanan berbeda.
"""
    chunks = chunk_document(text, source="test.md", target_tokens=20)
    titles = [c.section_title for c in chunks if c.section_title]
    assert any("Bab 1" in (t or "") for t in titles) or any("Pengantar" in (t or "") for t in titles)


def test_long_text_creates_multiple_chunks():
    text = ("Kalimat panjang yang berulang. " * 200).strip()
    chunks = chunk_document(text, source="long.md", target_tokens=80, max_tokens=120)
    assert len(chunks) > 1


def test_extracts_figure_references():
    text = "Materi mengacu pada Gambar 3.2 dan Tabel 4 untuk konteks."
    chunks = chunk_document(text, source="t.md")
    refs = [r for c in chunks for r in c.referenced_figures]
    assert any("3.2" in r.lower() or "gambar" in r.lower() for r in refs)
