"""Stage 8 §1-2, §4 — HTTP load scenarios, saturation probes, soak.

Spec: docs/testplan/08-performance.md §1 (KM-PERF-001..005), §2 (KM-PERF-010..012),
§4 (KM-PERF-030..031).

Non-blocking stage. These are *bounded* probes (small concurrency, few rounds,
short soak — all overridable via ``KODMOD_PERF_*`` env) that:
  * record p50/p95/error-rate baselines into ``docs/testplan/baselines/``,
  * assert only generous ceilings so a real >25 % regression (Stage 10 /
    KM-READY-005) is what fails a release, not CI jitter.

LLM = ``llm-stub`` (~0 ms), so every number is framework / graph / DB /
checkpointer / serialisation overhead — never model latency (README §1.2).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.performance._util import (
    is_flat,
    is_monotonic_growth,
    run_load,
    soak,
)
from tests.performance.conftest import (
    HTTP_CONCURRENCY,
    HTTP_ROUNDS,
    SOAK_SECONDS,
)

pytestmark = [pytest.mark.perf, pytest.mark.slow, pytest.mark.asyncio(loop_scope="session")]

_UTTERANCES = [
    "jelaskan apa itu pecahan",
    "bagaimana cara menjumlahkan pecahan berbeda penyebut",
    "apa itu pecahan senilai",
    "beri aku contoh soal pecahan",
]


async def _pg_active_connections(client: httpx.AsyncClient) -> int:
    """Cheap proxy for pool pressure: ``/ready`` proves a session can be taken."""
    r = await client.get("/ready")
    return 1 if r.json().get("checks", {}).get("database") == "ok" else 0


# --------------------------------------------------------------------------- #
# KM-PERF-001 — tutoring turn  (blocked by #1 until /voice/text stops 500ing)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 — POST /voice/text 500s on student.profile / learning_profile assembly before the "
    "graph runs; KM-PERF-001 can only measure the error path until it is fixed"
)
async def test_km_perf_001_tutoring_turn(client, student_factory, auth_headers, record_baseline):  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    hdr = auth_headers(tok)
    i = {"n": 0}

    async def _call() -> int:
        i["n"] += 1
        r = await client.post(
            "/voice/text", headers=hdr, data={"text": _UTTERANCES[i["n"] % len(_UTTERANCES)]}
        )
        return r.status_code

    rep = await run_load(_call, concurrency=HTTP_CONCURRENCY, rounds=HTTP_ROUNDS)
    record_baseline("km-perf-001-tutoring", rep.as_metrics("tutoring"))

    assert rep.error_rate == 0.0, rep.status_counts()
    assert all(s == 200 for s in rep.statuses), rep.status_counts()
    assert rep.p95 < 2.5, f"p95 {rep.p95:.3f}s over 2.5s ceiling"


# --------------------------------------------------------------------------- #
# KM-PERF-003 — analytics read  (works today)
# --------------------------------------------------------------------------- #
async def test_km_perf_003_analytics_read(
    client, student_factory, seed_mastery, concept_ids, auth_headers, record_baseline
):  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    hdr = auth_headers(tok)
    await seed_mastery(st.id, {concept_ids["pecahan"]: 0.55, concept_ids["fotosintesis"]: 0.8})

    async def _call() -> int:
        r = await client.get(f"/analytics/student/{st.id}", headers=hdr)
        return r.status_code

    rep = await run_load(_call, concurrency=HTTP_CONCURRENCY, rounds=HTTP_ROUNDS)
    record_baseline("km-perf-003-analytics", rep.as_metrics("analytics"))

    assert rep.error_rate == 0.0, rep.status_counts()
    assert all(s == 200 for s in rep.statuses), rep.status_counts()
    assert rep.p95 < 1.5, f"p95 {rep.p95:.3f}s over 1.5s ceiling"


# --------------------------------------------------------------------------- #
# KM-PERF-004 — content retrieve  (stub embeddings, unauth path)
# --------------------------------------------------------------------------- #
async def test_km_perf_004_content_retrieve(client, record_baseline):  # type: ignore[no-untyped-def]
    async def _call() -> int:
        r = await client.post(
            "/content/retrieve",
            json={"query": "apa itu pecahan senilai", "top_k": 4, "language": "id"},
        )
        return r.status_code

    rep = await run_load(_call, concurrency=HTTP_CONCURRENCY, rounds=HTTP_ROUNDS)
    record_baseline("km-perf-004-retrieve", rep.as_metrics("retrieve"))

    assert rep.error_rate == 0.0, rep.status_counts()
    assert all(s == 200 for s in rep.statuses), rep.status_counts()
    assert rep.p95 < 1.5, f"p95 {rep.p95:.3f}s over 1.5s ceiling"


# --------------------------------------------------------------------------- #
# KM-PERF-005 — realistic mix  (70 % tutoring / 20 % analytics / 10 % quiz)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 / #5 / #11 — the realistic mix includes /voice/text and /quiz/*, which 500 today; "
    "run for full effect once those journeys are green"
)
async def test_km_perf_005_realistic_mix(
    client, student_factory, seed_mastery, concept_ids, auth_headers, record_baseline
):  # type: ignore[no-untyped-def]
    st, tok = await student_factory()
    hdr = auth_headers(tok)
    await seed_mastery(st.id, {concept_ids["pecahan"]: 0.5})
    seq = ["tutor"] * 7 + ["analytics"] * 2 + ["quiz"] * 1
    i = {"n": 0}

    async def _call() -> int:
        i["n"] += 1
        kind = seq[i["n"] % len(seq)]
        if kind == "tutor":
            r = await client.post(
                "/voice/text", headers=hdr, data={"text": _UTTERANCES[i["n"] % 4]}
            )
        elif kind == "analytics":
            r = await client.get(f"/analytics/student/{st.id}", headers=hdr)
        else:
            r = await client.post(
                "/quiz/start",
                headers=hdr,
                json={
                    "student_id": str(st.id),
                    "concept_id": concept_ids["pecahan"],
                    "n_questions": 3,
                    "difficulty": "easy",
                },
            )
        return r.status_code

    rep = await run_load(_call, concurrency=HTTP_CONCURRENCY, rounds=HTTP_ROUNDS)
    record_baseline("km-perf-005-mixed", rep.as_metrics("mixed"))

    assert rep.error_rate == 0.0, rep.status_counts()
    assert rep.p95 < 3.0, f"aggregate p95 {rep.p95:.3f}s over 3.0s ceiling"


# --------------------------------------------------------------------------- #
# KM-PERF-010 — connection-pool saturation knee
# --------------------------------------------------------------------------- #
async def test_km_perf_010_pool_saturation(client, record_baseline):  # type: ignore[no-untyped-def]
    """Ramp concurrency on a DB-touching endpoint; find the knee where errors start.

    DB_POOL_SIZE=10 + max_overflow=20 -> ~30 concurrent sessions is the
    theoretical ceiling (database/session.py). We report the first VU count at
    which any request errors or 5xxs; below that the server must stay clean.
    """
    knee: int | None = None
    per_step: dict[int, dict] = {}
    for vu in (5, 10, 20, 30, 40):

        async def _call() -> int:
            r = await client.get("/ready")
            return r.status_code

        rep = await run_load(_call, concurrency=vu, rounds=2)
        per_step[vu] = rep.as_metrics()
        has_5xx = any(s >= 500 for s in rep.statuses)
        if (rep.errors or has_5xx) and knee is None:
            knee = vu

    record_baseline("km-perf-010-pool", {"knee_vu": knee, "steps": per_step})

    # The server must remain responsive afterwards regardless of the knee.
    assert (await client.get("/live")).status_code == 200
    # Below the pool ceiling (30) there must be no errors at all.
    for vu in (5, 10, 20):
        assert per_step[vu]["error_rate"] == 0.0, per_step[vu]
        assert not per_step[vu]["status_counts"].get(500), per_step[vu]


# --------------------------------------------------------------------------- #
# KM-PERF-011 — checkpointer write amplification per tutoring turn
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#1 — a tutoring turn 500s before graph.ainvoke, so no checkpoint rows are written and "
    "write amplification per turn cannot be measured end-to-end yet"
)
async def test_km_perf_011_checkpoint_write_amplification(
    client, student_factory, auth_headers, record_baseline
):  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from database.session import async_session, init_db

    await init_db()

    async def _count() -> int:
        async with async_session() as s:
            return int((await s.execute(text("SELECT count(*) FROM checkpoints"))).scalar_one())

    _st, tok = await student_factory()
    before = await _count()
    r = await client.post(
        "/voice/text", headers=auth_headers(tok), data={"text": "jelaskan pecahan"}
    )
    assert r.status_code == 200
    after = await _count()

    written = after - before
    record_baseline("km-perf-011-checkpoint", {"checkpoint_rows_per_turn": written})
    # A ~6-node path should not explode into hundreds of checkpoint rows.
    assert 1 <= written <= 40, f"{written} checkpoint rows for one turn"


# --------------------------------------------------------------------------- #
# KM-PERF-012 — host api RSS stays bounded under load
# --------------------------------------------------------------------------- #
async def test_km_perf_012_api_rss_plateau(client, record_baseline):  # type: ignore[no-untyped-def]
    psutil = pytest.importorskip("psutil")
    from pathlib import Path

    pid_file = Path(__file__).resolve().parents[2] / "reports" / ".api.pid"
    if not pid_file.exists():
        pytest.skip("no reports/.api.pid — api not started by the stage runner")
    try:
        proc = psutil.Process(int(pid_file.read_text().strip()))
    except (psutil.NoSuchProcess, ValueError) as exc:  # pragma: no cover
        pytest.skip(f"api pid not resolvable: {exc}")

    async def _call() -> int:
        r = await client.post(
            "/content/retrieve", json={"query": "pecahan", "top_k": 4, "language": "id"}
        )
        return r.status_code

    samples: list[float] = [proc.memory_info().rss / 1e6]
    for _ in range(5):
        await run_load(_call, concurrency=HTTP_CONCURRENCY, rounds=2)
        samples.append(proc.memory_info().rss / 1e6)

    record_baseline("km-perf-012-rss", {"rss_mb_samples": [round(s, 1) for s in samples]})
    # RSS may climb then plateau; it must not grow monotonically across every step.
    assert not is_monotonic_growth(samples), f"RSS climbs every step: {samples}"


# --------------------------------------------------------------------------- #
# KM-PERF-030 — soak: metrics flat, no resource leak
# --------------------------------------------------------------------------- #
async def test_km_perf_030_soak(client, record_baseline):  # type: ignore[no-untyped-def]
    """Constant mixed read load for KODMOD_PERF_SOAK_SECONDS; snapshot every 5 s.

    Uses only the endpoints that work today (analytics needs a token; content is
    unauth) so a leak — not #1 — is what this catches.
    """
    from pathlib import Path

    psutil = pytest.importorskip("psutil")
    pid_file = Path(__file__).resolve().parents[2] / "reports" / ".api.pid"
    proc = None
    if pid_file.exists():
        try:
            proc = psutil.Process(int(pid_file.read_text().strip()))
        except Exception:
            proc = None

    async def _call() -> int:
        r = await client.post(
            "/content/retrieve", json={"query": "pecahan senilai", "top_k": 4, "language": "id"}
        )
        return r.status_code

    async def _snapshot() -> dict:
        db_ok = await _pg_active_connections(client)
        rss = proc.memory_info().rss / 1e6 if proc else None
        return {"db_ok": db_ok, "rss_mb": round(rss, 1) if rss else None}

    rep, snaps = await soak(
        _call,
        seconds=SOAK_SECONDS,
        concurrency=max(4, HTTP_CONCURRENCY // 2),
        snapshot=_snapshot,
        snapshot_every=5.0,
    )
    record_baseline(
        "km-perf-030-soak",
        {"soak_seconds": SOAK_SECONDS, "snapshots": snaps, **rep.as_metrics("soak")},
    )

    assert rep.error_rate < 0.01, rep.status_counts()
    rss_series = [s["rss_mb"] for s in snaps if s.get("rss_mb") is not None]
    if len(rss_series) >= 3:
        assert not is_monotonic_growth(rss_series), f"RSS grows every snapshot: {rss_series}"
        assert is_flat(rss_series, tolerance=0.5), f"RSS not flat over soak: {rss_series}"


# --------------------------------------------------------------------------- #
# KM-PERF-031 — recovery after a spike
# --------------------------------------------------------------------------- #
async def test_km_perf_031_recovery_after_spike(client, record_baseline):  # type: ignore[no-untyped-def]
    async def _call() -> int:
        r = await client.post(
            "/content/retrieve", json={"query": "pecahan", "top_k": 4, "language": "id"}
        )
        return r.status_code

    baseline = await run_load(_call, concurrency=5, rounds=3)
    spike = await run_load(_call, concurrency=HTTP_CONCURRENCY * 3, rounds=3)
    await asyncio.sleep(2.0)
    recovered = await run_load(_call, concurrency=5, rounds=3)

    record_baseline(
        "km-perf-031-recovery",
        {
            "baseline": baseline.as_metrics("base"),
            "spike": spike.as_metrics("spike"),
            "recovered": recovered.as_metrics("recovered"),
        },
    )

    assert (await client.get("/live")).status_code == 200
    assert recovered.error_rate == 0.0, recovered.status_counts()
    # Latency must return to within 3x of the pre-spike baseline.
    assert recovered.p95 <= max(baseline.p95 * 3.0, 1.0), (
        f"recovered p95 {recovered.p95:.3f}s vs baseline {baseline.p95:.3f}s"
    )
