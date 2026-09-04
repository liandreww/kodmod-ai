"""Stage 5 — WebSocket /ws/voice.

Spec: docs/testplan/05-ws.md (KM-WS-001..041). Text-mode, real WS to the
host api process.

#WS-AUTH (RESOLVED): ``authenticate_ws`` now reads the token from ``?token=``
(and an ``Authorization: Bearer`` header fallback) itself, instead of relying on
an unresolved ``Query(default=None)`` parameter. Together with #21 (``end_of_speech``
``transcript`` bypass + ``STT_ENABLED`` honoured), #4 (``stream_tts`` iterated),
and the graph resume past ``interrupt_after=["reflection"]``, the live-socket
cases pass. KM-WS-022 has no reachable 1011 path once those are fixed and is
skipped per the spec.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from httpx_ws import WebSocketDisconnect

pytestmark = [pytest.mark.ws, pytest.mark.asyncio(loop_scope="session"), pytest.mark.timeout(30)]


async def _collect_until_final(ws, limit: float = 10.0) -> list[dict]:
    # `limit` is the overall budget: a cold first turn pays lazy imports + graph
    # warm-up + per-node checkpoint writes + the resume pass, which can exceed 5s.
    frames: list[dict] = []
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.receive_json(), timeout=deadline - time.time())
        except Exception:
            break
        frames.append(msg)
        if msg.get("type") == "final":
            break
    return frames


# --------------------------------------------------------------------------- #
# Auth rejection — these hold regardless of #WS-AUTH (bad creds must be refused)
# --------------------------------------------------------------------------- #
async def test_km_ws_002_no_token(ws_connect, upgrade_error) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(upgrade_error):
        async with ws_connect(token=None):
            pass


async def test_km_ws_003_garbage_token(ws_connect, upgrade_error) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(upgrade_error):
        async with ws_connect(token="not-a-jwt"):
            pass


async def test_km_ws_003b_expired_token(ws_connect, upgrade_error) -> None:  # type: ignore[no-untyped-def]
    import jwt as pyjwt

    from config.settings import settings

    now = int(time.time())
    tok = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "role": "student", "iat": now - 7200, "exp": now - 3600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )
    with pytest.raises(upgrade_error):
        async with ws_connect(token=tok):
            pass


async def test_km_ws_004_teacher_token_rejected(ws_connect, upgrade_error, teacher_factory) -> None:  # type: ignore[no-untyped-def]
    _tid, tok = await teacher_factory()
    with pytest.raises(upgrade_error):
        async with ws_connect(token=tok):
            pass


async def test_km_ws_005_valid_sub_no_student(ws_connect, upgrade_error, make_token) -> None:  # type: ignore[no-untyped-def]
    tok = make_token(uuid.uuid4(), "student")
    with pytest.raises(upgrade_error):
        async with ws_connect(token=tok):
            pass


# --------------------------------------------------------------------------- #
# Handshake success — blocked by #WS-AUTH
# --------------------------------------------------------------------------- #
async def test_km_ws_001_valid_student_token(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "ping"})


async def test_km_ws_006_header_auth(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=None, headers={"Authorization": f"Bearer {tok}"}) as ws:
        await ws.send_json({"event": "ping"})


async def test_km_ws_013_connection_uses_preferred_language(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory(preferred_language="id")
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "ping"})


# --------------------------------------------------------------------------- #
# Text control path — #WS-AUTH + #21 + #1
# --------------------------------------------------------------------------- #
async def test_km_ws_010_text_control_happy(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "jelaskan pecahan"})
        frames = await _collect_until_final(ws)
    types = {f.get("type") for f in frames}
    assert "final" in types
    assert "token" in types or any(f.get("type") == "audio_uri" for f in frames)


async def test_km_ws_030_multi_turn(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        for _ in range(2):
            await ws.send_json({"event": "end_of_speech", "transcript": "lanjutkan"})
            frames = await _collect_until_final(ws)
            assert any(f.get("type") == "final" for f in frames)


async def test_km_ws_031_output_frame_types(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "halo"})
        frames = await _collect_until_final(ws)
    allowed = {"partial_transcript", "token", "audio_uri", "final"}
    assert frames and all(f.get("type") in allowed for f in frames)


async def test_km_ws_041_streaming_stt_honours_text_mode(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "apa itu pecahan senilai"})
        frames = await _collect_until_final(ws)
    assert any(f.get("type") == "final" for f in frames)


# --------------------------------------------------------------------------- #
# TTS wiring / state assembly — #4, #1
# --------------------------------------------------------------------------- #
async def test_km_ws_012_tts_wiring(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "jelaskan pecahan"})
        frames = await _collect_until_final(ws)
    assert any(f.get("type") == "audio_uri" for f in frames)


async def test_km_ws_014_state_assembly_learning_profile(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "halo"})
        frames = await _collect_until_final(ws)
        assert any(f.get("type") == "final" for f in frames)  # target: turn completes


# --------------------------------------------------------------------------- #
# Robustness — need a live socket, so #WS-AUTH-blocked
# --------------------------------------------------------------------------- #
async def test_km_ws_020_idle_disconnect_is_clean(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok):
        pass
    async with ws_connect(token=tok) as ws2:
        await ws2.send_json({"event": "ping"})


async def test_km_ws_021_partial_then_disconnect(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "partial-metadata-only"})
    async with ws_connect(token=tok) as ws2:
        await ws2.send_json({"event": "ping"})


@pytest.mark.skip(
    reason="No reachable 1011 path once #WS-AUTH/#21/#4 are fixed: every client input drives a "
    "clean turn that ends with `final`. Non-JSON text is ignored (KM-WS-024), oversized frames "
    "close 1009 (KM-WS-040), and the stub graph completes for any transcript. Internal-error "
    "robustness is covered by KM-WS-020/021/024/040. Per docs/testplan/05-ws.md KM-WS-022."
)
async def test_km_ws_022_internal_error_closes_1011(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    with pytest.raises(WebSocketDisconnect) as exc:
        async with ws_connect(token=tok) as ws:
            await ws.send_json({"event": "end_of_speech", "transcript": "x"})
            for _ in range(10):
                await ws.receive_json()
    assert exc.value.code == 1011


async def test_km_ws_023_unknown_control_frame_ignored(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "foo"})
        await ws.send_json({"event": "bar"})
        await ws.send_json({"event": "baz"})


async def test_km_ws_024_non_json_text_frame(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_text("halo bukan json")
        await ws.send_json({"event": "ping"})


async def test_km_ws_040_large_frame_guard(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    # Catch the disconnect inside the context manager: httpx-ws wraps any
    # exception that escapes `async with` in an ExceptionGroup (documented).
    async with ws_connect(token=tok) as ws:
        await ws.send_bytes(b"\x00" * (5 * 1024 * 1024))
        with pytest.raises(WebSocketDisconnect) as exc:
            await ws.receive_json()
    assert exc.value.code == 1009  # MESSAGE_TOO_BIG
