"""Stage 5 — the streaming chat socket (`/ws/chat`).

Spec: docs/testplan/05-ws.md (KM-WS-001..017).

Text in, text out. There is no audio on this socket at all: speech recognition
and synthesis both happen in the browser, so a binary frame is simply not part
of the protocol.
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = [pytest.mark.ws, pytest.mark.asyncio(loop_scope="session")]

RECV_TIMEOUT = 60.0


async def _drain(ws, *, until: str = "final", timeout: float = RECV_TIMEOUT) -> list[dict]:
    """Collect frames until `until` (or `error`) arrives."""
    frames: list[dict] = []
    while True:
        frame = json.loads(await ws.receive_text(timeout=timeout))
        frames.append(frame)
        if frame.get("type") in {until, "error"}:
            return frames


def _types(frames: list[dict]) -> list[str]:
    return [f.get("type") for f in frames]


# --------------------------------------------------------------------------- #
# Handshake auth (KM-WS-001..006)
# --------------------------------------------------------------------------- #
async def test_km_ws_001_missing_token_is_refused(ws_connect, upgrade_error) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(upgrade_error):
        async with ws_connect():
            pass


async def test_km_ws_002_garbage_token_is_refused(ws_connect, upgrade_error) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(upgrade_error):
        async with ws_connect(token="not.a.jwt"):
            pass


async def test_km_ws_003_expired_token_is_refused(  # type: ignore[no-untyped-def]
    ws_connect, upgrade_error, student_factory, make_token
) -> None:
    student, _ = await student_factory()
    with pytest.raises(upgrade_error):
        async with ws_connect(token=make_token(student.id, "student", ttl_s=-60)):
            pass


async def test_km_ws_004_teacher_token_is_refused(  # type: ignore[no-untyped-def]
    ws_connect, upgrade_error, teacher_factory
) -> None:
    """The chat socket is a learner surface; a teacher token must not open it."""
    _teacher, token = await teacher_factory()
    with pytest.raises(upgrade_error):
        async with ws_connect(token=token):
            pass


async def test_km_ws_005_token_for_nobody_is_refused(  # type: ignore[no-untyped-def]
    ws_connect, upgrade_error, make_token
) -> None:
    with pytest.raises(upgrade_error):
        async with ws_connect(token=make_token(uuid.uuid4(), "student")):
            pass


async def test_km_ws_006_valid_student_token_connects(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(await ws.receive_text(timeout=10.0))["type"] == "pong"


# --------------------------------------------------------------------------- #
# One turn (KM-WS-010..017)
# --------------------------------------------------------------------------- #
async def test_km_ws_010_turn_returns_session_then_final(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": "Apa itu pecahan?"}))
        frames = await _drain(ws)

    kinds = _types(frames)
    assert kinds[0] == "session", "the client needs the session id before anything else"
    assert kinds[-1] == "final"

    session_id = frames[0]["session_id"]
    uuid.UUID(session_id)  # must be a real id the client can send back

    final = frames[-1]
    assert final["session_id"] == session_id
    assert isinstance(final["text"], str) and final["text"].strip()
    assert isinstance(final["sources"], list)
    assert final["latency_ms"] >= 0


async def test_km_ws_011_final_text_is_the_accessible_text(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    """Whatever reaches the student has been through the accessibility pass."""
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": "Jelaskan pecahan."}))
        frames = await _drain(ws)

    text = frames[-1]["text"]
    assert "<break" not in text, "pacing markup would be displayed verbatim"
    assert "**" not in text, "markdown would be read out as asterisks"


async def test_km_ws_012_session_id_is_reused_across_turns(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": "Halo."}))
        first = await _drain(ws)
        session_id = first[0]["session_id"]

        await ws.send_text(
            json.dumps({"type": "message", "text": "Lanjutkan.", "session_id": session_id})
        )
        second = await _drain(ws)

    assert second[0]["session_id"] == session_id


async def test_km_ws_013_empty_message_is_an_error_not_a_turn(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": "   "}))
        frame = json.loads(await ws.receive_text(timeout=10.0))
    assert frame["type"] == "error"
    assert frame["message"]


async def test_km_ws_014_oversized_message_is_rejected(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": "a" * 5000}))
        frame = json.loads(await ws.receive_text(timeout=10.0))
    assert frame["type"] == "error"


async def test_km_ws_015_unknown_frame_type_is_rejected(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "sing", "text": "halo"}))
        frame = json.loads(await ws.receive_text(timeout=10.0))
    assert frame["type"] == "error"


async def test_km_ws_016_socket_survives_an_error_frame(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    """One bad frame must not end the conversation."""
    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": ""}))
        assert json.loads(await ws.receive_text(timeout=10.0))["type"] == "error"

        await ws.send_text(json.dumps({"type": "message", "text": "Apa itu pecahan?"}))
        frames = await _drain(ws)
    assert _types(frames)[-1] == "final"


async def test_km_ws_017_turn_is_persisted_as_a_transcript(ws_connect, student_factory) -> None:  # type: ignore[no-untyped-def]
    """Both sides of the turn must land in interaction_logs for the teacher view."""
    from sqlalchemy import text

    from database.session import async_session

    _student, token = await student_factory()
    async with ws_connect(token=token) as ws:
        await ws.send_text(json.dumps({"type": "message", "text": "Apa itu pecahan?"}))
        frames = await _drain(ws)
    session_id = frames[0]["session_id"]

    async with async_session() as s:
        roles = (
            (
                await s.execute(
                    text(
                        "SELECT role FROM interaction_logs "
                        "WHERE session_id = CAST(:sid AS uuid) ORDER BY timestamp"
                    ),
                    {"sid": session_id},
                )
            )
            .scalars()
            .all()
        )
    assert "student" in roles and "assistant" in roles
