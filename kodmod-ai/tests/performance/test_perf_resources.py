"""Stage 8 §2 — resource-level probes: Redis throughput, CPU profile.

Spec: docs/testplan/08-performance.md §2 (KM-PERF-013..014).

These call Python directly (Redis client / cProfile) — no ``api`` process
needed, only Redis from ``docker/docker-compose.test.yml``.
"""

from __future__ import annotations

import time

import pytest

pytestmark = [pytest.mark.perf, pytest.mark.slow, pytest.mark.asyncio(loop_scope="session")]


# --------------------------------------------------------------------------- #
# KM-PERF-013 — Redis throughput for short-term session writes
# --------------------------------------------------------------------------- #
async def test_km_perf_013_redis_throughput(redis_client, record_baseline):  # type: ignore[no-untyped-def]
    from memory import short_term

    session_id = "perf-redis"
    n = 200

    t0 = time.perf_counter()
    for i in range(n):
        await short_term.append_tutoring_turn(session_id, {"role": "user", "text": f"turn {i}"})
    write_dt = time.perf_counter() - t0

    t1 = time.perf_counter()
    for i in range(n):
        await short_term.set_pacing(session_id, 0.8 + (i % 3) * 0.1)
    pacing_dt = time.perf_counter() - t1

    ops_per_s = (2 * n) / max(write_dt + pacing_dt, 1e-6)
    info = await redis_client.info("commandstats") if hasattr(redis_client, "info") else {}

    record_baseline(
        "km-perf-013-redis",
        {
            "n": n,
            "append_turn_s": round(write_dt, 3),
            "set_pacing_s": round(pacing_dt, 3),
            "ops_per_s": round(ops_per_s, 1),
            "commandstats_keys": len(info) if isinstance(info, dict) else 0,
        },
    )

    # Local Redis over a published port: a few hundred ops/s is a very soft floor.
    assert ops_per_s > 100, f"redis throughput {ops_per_s:.0f} ops/s below floor"


# --------------------------------------------------------------------------- #
# KM-PERF-014 — CPU profile of a hot pure path (informational)
# --------------------------------------------------------------------------- #
async def test_km_perf_014_cpu_profile_dump(record_baseline):  # type: ignore[no-untyped-def]
    import cProfile
    import io
    import pstats

    from rag.chunking import chunk_document

    doc = (
        ("Pecahan senilai dijelaskan panjang lebar dalam modul ini. " * 400)
        + "\n\n## Bagian\n\n"
        + ("Menyamakan penyebut adalah langkah pertama sebelum menjumlahkan. " * 400)
    )

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(20):
        chunk_document(doc, source="perf")
    pr.disable()

    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(8)
    top = buf.getvalue()

    record_baseline("km-perf-014-cprofile", {"top_functions": top[:2000]})
    assert "function calls" in top
