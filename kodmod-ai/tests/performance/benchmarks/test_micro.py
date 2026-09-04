"""Stage 8 §5 — micro-benchmarks (pytest-benchmark).

Spec: docs/testplan/08-performance.md §5 (KM-PERF-040..045).

Pure, in-process, no service needed. Each case pins a baseline into
``docs/testplan/baselines/bench.json`` (the stage runner passes
``--benchmark-json=...``); Stage 10 / KM-READY-005 fails a release if any of
these regress by more than +25 % vs the stored baseline.

Run just these:
    pytest tests/performance/benchmarks -m perf \
        --benchmark-json=docs/testplan/baselines/bench.json
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_benchmark")

pytestmark = [pytest.mark.perf]


# --------------------------------------------------------------------------- #
# KM-PERF-040 — rag.chunking.chunk_document on a ~2000-word document
# --------------------------------------------------------------------------- #
_DOC_2000_WORDS = (
    "# Pecahan\n\n"
    + (
        "Pecahan adalah bagian dari keseluruhan yang dinyatakan sebagai pembilang per penyebut. "
        * 40
    )
    + "\n\n## Pecahan Senilai\n\n"
    + ("Dua pecahan senilai jika hasil kali silang pembilang dan penyebutnya sama besar. " * 40)
    + "\n\n## Penjumlahan\n\n"
    + (
        "Untuk menjumlahkan pecahan berpenyebut beda, samakan penyebut lalu jumlahkan pembilang. "
        * 40
    )
)


def test_km_perf_040_chunk_document(benchmark) -> None:  # type: ignore[no-untyped-def]
    from rag.chunking import chunk_document

    benchmark.group = "KM-PERF-040 chunk_document"
    chunks = benchmark(chunk_document, _DOC_2000_WORDS, source="perf-doc")
    assert chunks and all(c.text for c in chunks)


# --------------------------------------------------------------------------- #
# KM-PERF-041 — deterministic stub embed_text, batch of 16
# --------------------------------------------------------------------------- #
def test_km_perf_041_stub_embed_batch16(benchmark) -> None:  # type: ignore[no-untyped-def]
    from tests._fakes.fake_embeddings import fake_embed_text_sync

    batch = [f"kalimat contoh nomor {i} tentang pecahan senilai" for i in range(16)]
    benchmark.group = "KM-PERF-041 stub embed batch16"
    vecs = benchmark(fake_embed_text_sync, batch)
    assert len(vecs) == 16 and len(vecs[0]) >= 256


# --------------------------------------------------------------------------- #
# KM-PERF-042 — agents.scoring_agent._score_mcq
# --------------------------------------------------------------------------- #
def test_km_perf_042_score_mcq(benchmark) -> None:  # type: ignore[no-untyped-def]
    from agents.scoring_agent import _score_mcq

    opts = ["A. 1/2", "B. 2/4", "C. 3/4", "D. 1/4"]
    benchmark.group = "KM-PERF-042 _score_mcq"
    score, _fb = benchmark(_score_mcq, "jawaban B", "B", opts)
    assert score == 1.0


# --------------------------------------------------------------------------- #
# KM-PERF-043 — graphs.main_graph.route_after_intent
# --------------------------------------------------------------------------- #
def test_km_perf_043_route_after_intent(benchmark) -> None:  # type: ignore[no-untyped-def]
    from graphs.main_graph import route_after_intent

    state = {
        "intent": "quiz",
        "quiz_session_id": "s1",
        "quiz_questions": [{"id": "q1"}, {"id": "q2"}],
        "current_question_index": 0,
        "student_answer": "A",
    }
    benchmark.group = "KM-PERF-043 route_after_intent"
    dest = benchmark(route_after_intent, state)
    assert dest == "scoring"


# --------------------------------------------------------------------------- #
# KM-PERF-044 — graphs.state.initial_state
# --------------------------------------------------------------------------- #
def test_km_perf_044_initial_state(benchmark) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    benchmark.group = "KM-PERF-044 initial_state"
    st = benchmark(initial_state, "sess-perf", "11111111-1111-1111-1111-111111111111")
    assert st["session_id"] == "sess-perf"


# --------------------------------------------------------------------------- #
# KM-PERF-045 — accessibility_agent fast-path pipeline on ~800 words
# --------------------------------------------------------------------------- #
_TEXT_800_WORDS = "**Perhatikan** diagram di atas. " + (
    "Seperti terlihat pada gambar, pecahan 1/2 setara dengan 2/4, dan hal ini penting sekali "
    "untuk dipahami sebelum melangkah ke penjumlahan pecahan berpenyebut berbeda karena "
    "tanpa pemahaman itu proses menyamakan penyebut akan terasa membingungkan. " * 30
)


def test_km_perf_045_accessibility_fast_path(benchmark) -> None:  # type: ignore[no-untyped-def]
    from accessibility.narration import describe_visuals_in_text
    from agents.accessibility_agent import (
        _add_ssml_breaks,
        _normalize_numbers,
        _replace_visual_refs,
        _split_long_sentences,
        _strip_markdown,
    )

    def _pipeline(text: str) -> str:
        out = _strip_markdown(text)
        out = _replace_visual_refs(out)
        out = describe_visuals_in_text(out)
        out = _split_long_sentences(out)
        out = _normalize_numbers(out)
        return _add_ssml_breaks(out)

    benchmark.group = "KM-PERF-045 accessibility fast-path"
    polished = benchmark(_pipeline, _TEXT_800_WORDS)
    assert "**" not in polished
