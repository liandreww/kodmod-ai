"""KM-UNIT-010..018 — RAG chunking (rag/chunking.py).

Spec: docs/testplan/01-unit.md §1.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from rag.chunking import _approx_tokens, _split_sentences, chunk_document, chunks_to_payloads

pytestmark = pytest.mark.unit


def test_simple_text_yields_at_least_one_chunk():  # KM-UNIT-010
    text = "Ini kalimat pertama. Ini kalimat kedua. Dan kalimat ketiga."
    chunks = chunk_document(text, source="test.md")
    assert len(chunks) >= 1
    assert all(c.text.strip() for c in chunks)
    assert all(c.source == "test.md" for c in chunks)


def test_respects_section_boundaries():  # KM-UNIT-011
    text = """# Bab 1: Pengantar
Kalimat dalam bab satu yang menjelaskan konsep.

## Bagian 1.1: Detail
Detail yang lebih dalam dan teknis.

# Bab 2: Lanjutan
Materi bab dua dengan penekanan berbeda.
"""
    chunks = chunk_document(text, source="test.md", target_tokens=20)
    titles = [c.section_title for c in chunks if c.section_title]
    assert any("Bab 1" in (t or "") for t in titles) or any(
        "Pengantar" in (t or "") for t in titles
    )


def test_long_text_creates_multiple_chunks():  # KM-UNIT-012
    text = ("Kalimat panjang yang berulang. " * 200).strip()
    chunks = chunk_document(text, source="long.md", target_tokens=80, max_tokens=120)
    assert len(chunks) >= 3
    assert all(_approx_tokens(c.text) <= 120 + 20 for c in chunks)  # ~max_tokens + one sentence


def test_extracts_figure_references():  # KM-UNIT-013
    text = "Materi mengacu pada Gambar 3.2 dan Tabel 4 untuk konteks."
    chunks = chunk_document(text, source="t.md")
    refs = " ".join(r for c in chunks for r in c.referenced_figures).lower()
    assert "3.2" in refs
    assert "tabel 4" in refs or "4" in refs


def test_sentence_overlap_between_consecutive_chunks():  # KM-UNIT-014
    text = "Kalimat satu. Kalimat dua. Kalimat tiga. Kalimat empat. Kalimat lima."
    chunks = chunk_document(
        text, source="o.md", target_tokens=6, max_tokens=10, overlap_sentences=1
    )
    assert len(chunks) >= 2
    for prev, nxt in pairwise(chunks):
        last_sentence = _split_sentences(prev.text)[-1]
        assert nxt.text.startswith(last_sentence)


def test_flush_preserves_all_sentences():  # KM-UNIT-015
    sentences = [f"Kalimat nomor {i} di sini." for i in range(1, 9)]
    text = " ".join(sentences)
    chunks = chunk_document(
        text, source="f.md", target_tokens=8, max_tokens=14, overlap_sentences=1
    )
    joined = " ".join(c.text for c in chunks)
    for s in sentences:
        assert s in joined  # nothing dropped by the flush() branch


@pytest.mark.parametrize("text", ["", "   \n\t  "])
def test_empty_or_whitespace_input(text: str):  # KM-UNIT-016
    assert chunk_document(text, source="s") == []  # no IndexError


def test_chunks_to_payloads_shape():  # KM-UNIT-017
    chunks = chunk_document("Satu kalimat saja di sini.", source="p.md")
    payloads = chunks_to_payloads(chunks)
    assert payloads
    for p in payloads:
        assert set(p) >= {
            "text",
            "source",
            "section_title",
            "chunk_index",
            "referenced_figures",
        }


def test_approx_tokens():  # KM-UNIT-018
    assert _approx_tokens("a" * 400) == 100  # len // 4
    assert _approx_tokens("") == 1  # min 1
