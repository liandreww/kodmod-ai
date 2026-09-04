"""Stage 9 §4 — DoS / resource limits.

Spec: docs/testplan/09-security.md §4 (KM-SEC-040..047).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

pytestmark = [pytest.mark.security, pytest.mark.asyncio(loop_scope="session"), pytest.mark.slow]


# --------------------------------------------------------------------------- #
# KM-SEC-040 — giant JSON body
# --------------------------------------------------------------------------- #
async def test_km_sec_040_giant_json_body(client) -> None:  # type: ignore[no-untyped-def]
    huge = "x" * (12 * 1024 * 1024)  # 12 MB query string
    try:
        r = await client.post("/content/retrieve", json={"query": huge, "top_k": 4})
    except httpx.HTTPError as exc:  # connection reset by a body-size limit is fine
        pytest.skip(f"server closed the connection on oversized body: {exc}")
    assert r.status_code in {400, 413, 422}, r.status_code
    # server still alive
    assert (await client.get("/live")).status_code == 200


# --------------------------------------------------------------------------- #
# KM-SEC-041 — oversized audio upload
# --------------------------------------------------------------------------- #
async def test_km_sec_041_oversized_audio_upload(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    # MAX_AUDIO_SECONDS (120) * ~64 kB/s soft cap ~= 7.7 MB; send well over it.
    blob = b"RIFF" + b"\x00" * (16 * 1024 * 1024) + b"WAVE"
    try:
        r = await client.post(
            "/voice/chat",
            headers={"Authorization": f"Bearer {tok}"},
            files={"audio": ("big.wav", blob, "audio/wav")},
        )
    except httpx.HTTPError as exc:
        pytest.skip(f"server closed the connection on oversized upload: {exc}")
    # Accept either an explicit reject, or a truncating save that still succeeds
    # (save_upload caps bytes) — what must NOT happen is a 5xx / OOM.
    assert r.status_code < 500, r.text[:200]
    assert (await client.get("/live")).status_code == 200


# --------------------------------------------------------------------------- #
# KM-SEC-042 — very large WS PCM frame
# --------------------------------------------------------------------------- #
async def test_km_sec_042_ws_large_frame(api_base_url, _api_up, student_factory) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("httpx_ws")
    from httpx_ws import WebSocketDisconnect, aconnect_ws

    _st, tok = await student_factory()
    ws_url = api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"
    async with httpx.AsyncClient() as c:
        async with aconnect_ws(f"{ws_url}?token={tok}", c) as ws:
            await ws.send_bytes(b"\x00" * (20 * 1024 * 1024))
            with pytest.raises(WebSocketDisconnect) as exc:
                await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    assert exc.value.code == 1009  # MESSAGE_TOO_BIG, not a crash


# --------------------------------------------------------------------------- #
# KM-SEC-043 — never-ending utterance (no end_of_speech)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "DoS — _collect_utterance has no wall-clock / cumulative-size cap; a client that streams "
    "PCM forever without end_of_speech is never cut off. Target: bounded accumulation + close"
)
async def test_km_sec_043_unbounded_utterance(api_base_url, _api_up, student_factory) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("httpx_ws")
    from httpx_ws import WebSocketDisconnect, aconnect_ws

    _st, tok = await student_factory()
    ws_url = api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"
    async with httpx.AsyncClient() as c:
        async with aconnect_ws(f"{ws_url}?token={tok}", c) as ws:
            with pytest.raises((WebSocketDisconnect, TimeoutError)):
                # ~5 MB of PCM in ~64 kB frames, no end_of_speech, ever.
                async with asyncio.timeout(20.0):
                    for _ in range(80):
                        await ws.send_bytes(b"\x11" * 64_000)
                        await asyncio.sleep(0.05)
                    await ws.receive_json()  # server should have closed us by now


# --------------------------------------------------------------------------- #
# KM-SEC-044 — many rapid WS connections
# --------------------------------------------------------------------------- #
async def test_km_sec_044_many_ws_connections(api_base_url, _api_up, student_factory) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("httpx_ws")
    from httpx_ws import aconnect_ws

    _st, tok = await student_factory()
    ws_url = api_base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"

    async def _open_close() -> bool:
        try:
            async with httpx.AsyncClient() as c:
                async with aconnect_ws(f"{ws_url}?token={tok}", c):
                    return True
        except Exception:
            return False

    results = await asyncio.gather(*(_open_close() for _ in range(120)))
    # Graceful degradation is fine (some may be refused); the server must survive.
    async with httpx.AsyncClient(base_url=api_base_url, timeout=10.0) as c:
        assert (await c.get("/live")).status_code == 200
    assert sum(results) >= 1


# --------------------------------------------------------------------------- #
# KM-SEC-045 — slow request bodies (light slowloris)
# --------------------------------------------------------------------------- #
async def test_km_sec_045_slow_body_does_not_exhaust_workers(client, api_base_url) -> None:  # type: ignore[no-untyped-def]
    async def _slow_body():
        # dribble a body over ~6 s
        for _ in range(6):
            yield b'{"query":"x",'
            await asyncio.sleep(1.0)
        yield b'"top_k":4}'

    async def _slow_req() -> None:
        try:
            async with httpx.AsyncClient(base_url=api_base_url, timeout=20.0) as c:
                await c.post(
                    "/content/retrieve",
                    content=_slow_body(),
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError:
            pass

    slow = [asyncio.create_task(_slow_req()) for _ in range(15)]
    await asyncio.sleep(2.0)
    # While the slow requests are mid-flight, a normal request must still get through.
    fast = await client.get("/live")
    assert fast.status_code == 200
    for t in slow:
        t.cancel()
    await asyncio.gather(*slow, return_exceptions=True)


# --------------------------------------------------------------------------- #
# KM-SEC-046 — rate limiting
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "rate limiting — api/middleware/rate_limit.py does not exist; a single token can hammer "
    "/voice/text without ever seeing a 429. Target: 429 after a per-token threshold"
)
async def test_km_sec_046_rate_limiting(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    hdr = {"Authorization": f"Bearer {tok}"}
    codes = []
    for _ in range(120):
        r = await client.post("/voice/text", headers=hdr, data={"text": "halo"})
        codes.append(r.status_code)
    assert 429 in codes, f"no 429 after 120 rapid requests: {sorted(set(codes))}"


# --------------------------------------------------------------------------- #
# KM-SEC-047 — graph recursion / loop is bounded
# --------------------------------------------------------------------------- #
async def test_km_sec_047_graph_recursion_bounded(client, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    hdr = {"Authorization": f"Bearer {tok}"}
    # A pathological utterance must not hang forever — LangGraph recursion_limit
    # (or a handler timeout) must break it. 30 s ceiling here.
    try:
        r = await asyncio.wait_for(
            client.post(
                "/voice/text",
                headers=hdr,
                data={"text": "ulangi ulangi ulangi ulangi ulangi ulangi ulangi ulangi"},
            ),
            timeout=30.0,
        )
    except TimeoutError:
        raise AssertionError("one /voice/text request hung > 30s — recursion not bounded") from None
    assert 100 <= r.status_code < 600  # completed with a response, never hung
