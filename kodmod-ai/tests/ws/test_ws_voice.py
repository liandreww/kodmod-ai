"""Stage 5 — WebSocket /ws/voice.

Spec: docs/testplan/05-ws.md (KM-WS-001..041). Text-mode, real WS to the
containerized api.

NEW FINDING (#WS-AUTH): ``voice_stream.voice_ws`` calls ``authenticate_ws(websocket)``
as a plain function, not a FastAPI dependency, so its
``token: str | None = Query(default=None)`` parameter is never resolved. Every
WS connection — even with a valid ``?token=`` — fails ``_decode_jwt`` and the
handshake is rejected 401. This blocks every case that needs a live socket, on
top of the pre-existing #1 (student.profile), #4 (stream_tts), #21 (StreamingSTT
ignores STT_ENABLED / no `transcript` field).
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from httpx_ws import WebSocketDisconnect

pytestmark = [pytest.mark.ws, pytest.mark.asyncio(loop_scope="session"), pytest.mark.timeout(20)]

WS_AUTH = (
    "#WS-AUTH — authenticate_ws is called as a plain function, not a Depends, so the "
    "?token= query param is never resolved; every WS handshake 401s"
)


async def _collect_until_final(ws, limit: float = 5.0) -> list[dict]:
    frames: list[dict] = []
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.receive_json(), timeout=limit)
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
@pytest.mark.known_bug(WS_AUTH)
async def test_km_ws_001_valid_student_token(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "ping"})


@pytest.mark.known_bug(
    "#17 — module docstring claims Authorization-header auth on the upgrade; authenticate_ws "
    "reads only ?token= (and #WS-AUTH means even that is unresolved)"
)
async def test_km_ws_006_header_auth(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=None, headers={"Authorization": f"Bearer {tok}"}) as ws:
        await ws.send_json({"event": "ping"})


@pytest.mark.known_bug(
    WS_AUTH + "; also #2 verify: StreamingSTT(language=student.preferred_language)"
)
async def test_km_ws_013_connection_uses_preferred_language(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory(preferred_language="id")
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "ping"})


# --------------------------------------------------------------------------- #
# Text control path — #WS-AUTH + #21 + #1
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    WS_AUTH + "; then #21 (no `transcript` on end_of_speech) + #1 (student.profile) block the turn"
)
async def test_km_ws_010_text_control_happy(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "jelaskan pecahan"})
        frames = await _collect_until_final(ws)
    types = {f.get("type") for f in frames}
    assert "final" in types
    assert "token" in types or any(f.get("type") == "audio_uri" for f in frames)


@pytest.mark.known_bug(WS_AUTH + "; #21 blocks multi-turn context over one connection")
async def test_km_ws_030_multi_turn(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        for _ in range(2):
            await ws.send_json({"event": "end_of_speech", "transcript": "lanjutkan"})
            frames = await _collect_until_final(ws)
            assert any(f.get("type") == "final" for f in frames)


@pytest.mark.known_bug(WS_AUTH + "; output frame taxonomy only checkable once the text path works")
async def test_km_ws_031_output_frame_types(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "halo"})
        frames = await _collect_until_final(ws)
    allowed = {"partial_transcript", "token", "audio_uri", "final"}
    assert frames and all(f.get("type") in allowed for f in frames)


@pytest.mark.known_bug(
    "#21 — _collect_utterance always builds StreamingSTT and ignores STT_ENABLED; an "
    "end_of_speech carrying `transcript` should bypass STT (blocked earlier by #WS-AUTH)"
)
async def test_km_ws_041_streaming_stt_honours_text_mode(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "apa itu pecahan senilai"})
        frames = await _collect_until_final(ws)
    assert any(f.get("type") == "final" for f in frames)


# --------------------------------------------------------------------------- #
# TTS wiring / state assembly — #4, #1
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    WS_AUTH + "; #4 — voice_ws calls stream_tts(websocket, text) but the signature is "
    "stream_tts(text, voice=None) -> AsyncIterator[bytes], never iterated"
)
async def test_km_ws_012_tts_wiring(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "jelaskan pecahan"})
        frames = await _collect_until_final(ws)
    assert any(f.get("type") == "audio_uri" for f in frames)


@pytest.mark.known_bug(
    WS_AUTH + "; #1 — per-utterance state does state['learning_profile'] = student.profile"
)
async def test_km_ws_014_state_assembly_learning_profile(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "end_of_speech", "transcript": "halo"})
        frames = await _collect_until_final(ws)
        assert any(f.get("type") == "final" for f in frames)  # target: turn completes


# --------------------------------------------------------------------------- #
# Robustness — need a live socket, so #WS-AUTH-blocked
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(WS_AUTH)
async def test_km_ws_020_idle_disconnect_is_clean(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok):
        pass
    async with ws_connect(token=tok) as ws2:
        await ws2.send_json({"event": "ping"})


@pytest.mark.known_bug(WS_AUTH)
async def test_km_ws_021_partial_then_disconnect(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "partial-metadata-only"})
    async with ws_connect(token=tok) as ws2:
        await ws2.send_json({"event": "ping"})


@pytest.mark.known_bug(WS_AUTH + "; also documents the 1011 mapping once a socket can open")
async def test_km_ws_022_internal_error_closes_1011(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    with pytest.raises(WebSocketDisconnect) as exc:
        async with ws_connect(token=tok) as ws:
            await ws.send_json({"event": "end_of_speech", "transcript": "x"})
            for _ in range(10):
                await ws.receive_json()
    assert exc.value.code == 1011


@pytest.mark.known_bug(WS_AUTH)
async def test_km_ws_023_unknown_control_frame_ignored(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_json({"event": "foo"})
        await ws.send_json({"event": "bar"})
        await ws.send_json({"event": "baz"})


@pytest.mark.known_bug(
    WS_AUTH + "; #24 — a non-JSON text frame makes _collect_utterance json.loads() raise "
    "and closes 1011 instead of being ignored"
)
async def test_km_ws_024_non_json_text_frame(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    async with ws_connect(token=tok) as ws:
        await ws.send_text("halo bukan json")
        await ws.send_json({"event": "ping"})


@pytest.mark.known_bug(WS_AUTH + "; #40 — no per-frame size guard on inbound PCM")
async def test_km_ws_040_large_frame_guard(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    with pytest.raises(WebSocketDisconnect):
        async with ws_connect(token=tok) as ws:
            await ws.send_bytes(b"\x00" * (5 * 1024 * 1024))
            await ws.receive_json()
