"""Stage 8 §3 — WebSocket concurrency & connection ramp.

Spec: docs/testplan/08-performance.md §3 (KM-PERF-020..021).

Text-mode: each connection sends one ``end_of_speech`` control frame carrying a
``transcript`` (same protocol as Stage 5, tests/ws/test_ws_voice.py) and waits
for the ``final`` frame. Bounded by ``KODMOD_PERF_WS_CONNECTIONS`` (default 20).
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from tests.performance.conftest import WS_CONNECTIONS

pytest.importorskip("httpx_ws")
from httpx_ws import aconnect_ws

pytestmark = [pytest.mark.perf, pytest.mark.slow, pytest.mark.asyncio(loop_scope="session")]


async def _one_turn(ws_url: str, token: str, *, budget: float = 15.0) -> tuple[bool, float]:
    """Open a socket, drive one text turn, return (saw_final, seconds_to_final)."""
    start = time.perf_counter()
    async with httpx.AsyncClient() as c:
        async with aconnect_ws(f"{ws_url}?token={token}", c) as ws:
            await ws.send_json({"event": "end_of_speech", "transcript": "jelaskan pecahan"})
            deadline = time.perf_counter() + budget
            while time.perf_counter() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.receive_json(), timeout=deadline - time.perf_counter()
                    )
                except Exception:
                    break
                if msg.get("type") == "final":
                    return True, time.perf_counter() - start
    return False, time.perf_counter() - start


# --------------------------------------------------------------------------- #
# KM-PERF-020 — N concurrent /ws/voice, one utterance each
# --------------------------------------------------------------------------- #
async def test_km_perf_020_ws_concurrency(api_base_url, _api_up, student_factory, record_baseline):  # type: ignore[no-untyped-def]
    ws_url = api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"
    pairs = [await student_factory() for _ in range(WS_CONNECTIONS)]

    results = await asyncio.gather(
        *(_one_turn(ws_url, tok) for _st, tok in pairs), return_exceptions=True
    )

    finals = [r for r in results if isinstance(r, tuple) and r[0]]
    latencies = sorted(r[1] for r in finals)
    errors = [r for r in results if not (isinstance(r, tuple) and r[0])]
    p95 = (
        latencies[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))] if latencies else None
    )

    record_baseline(
        "km-perf-020-ws",
        {
            "connections": WS_CONNECTIONS,
            "final_frames": len(finals),
            "errors": len(errors),
            "p95_to_final_s": round(p95, 2) if p95 is not None else None,
        },
    )

    assert len(finals) == WS_CONNECTIONS, f"{len(errors)}/{WS_CONNECTIONS} connections failed"
    assert p95 is not None and p95 < 5.0, f"p95 time-to-final {p95:.2f}s over 5s"


# --------------------------------------------------------------------------- #
# KM-PERF-021 — connection ramp: find where accept() starts failing
# --------------------------------------------------------------------------- #
async def test_km_perf_021_ws_connection_ramp(
    api_base_url, _api_up, student_factory, record_baseline
):  # type: ignore[no-untyped-def]
    ws_url = api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"
    _st, tok = await student_factory()
    target = max(WS_CONNECTIONS * 3, 60)

    opened: list = []
    stack: list = []
    fail_at: int | None = None
    try:
        for n in range(target):
            try:
                c = httpx.AsyncClient()
                cm = aconnect_ws(f"{ws_url}?token={tok}", c)
                ws = await cm.__aenter__()
                stack.append((c, cm))
                opened.append(ws)
            except Exception:
                fail_at = n
                break
    finally:
        for c, cm in reversed(stack):
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
            await c.aclose()

    record_baseline(
        "km-perf-021-ws-ramp",
        {"target": target, "opened": len(opened), "accept_failed_at": fail_at},
    )

    # A single uvicorn worker should comfortably hold this many idle sockets.
    assert len(opened) >= WS_CONNECTIONS * 2, f"only {len(opened)} sockets before accept failed"
    # Server still serves plain HTTP after the ramp.
    async with httpx.AsyncClient(base_url=api_base_url, timeout=10.0) as c:
        assert (await c.get("/live")).status_code == 200
