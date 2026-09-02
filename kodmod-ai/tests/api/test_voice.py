"""Stage 4 §8 — /voice endpoints (text-mode).

Spec: docs/testplan/04-api.md §8 (KM-API-080..084).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


@pytest.mark.known_bug(
    "#1 — POST /voice/text does state['learning_profile'] = student.profile; the ORM Student "
    "has no .profile attribute -> AttributeError 500"
)
async def test_km_api_080_voice_text(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/voice/text", headers=auth_headers(tok), data={"text": "jelaskan pecahan"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["response_text"]
    assert body["audio_uri"] == ""  # TTS disabled


async def test_km_api_081_voice_text_missing_field(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post("/voice/text", headers=auth_headers(tok), data={})
    assert r.status_code == 422


async def test_km_api_082_voice_chat_rejects_non_audio(
    client, student_factory, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/voice/chat",
        headers=auth_headers(tok),
        files={"audio": ("note.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


@pytest.mark.known_bug(
    "#1 — /voice/chat also hits student.profile -> 500 before any real processing"
)
async def test_km_api_083_voice_chat_audio_dummy(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/voice/chat",
        headers=auth_headers(tok),
        files={"audio": ("a.wav", b"RIFF\x00\x00\x00\x00WAVE", "audio/wav")},
    )
    assert r.status_code == 200
    assert "response_text" in r.json()


@pytest.mark.known_bug(
    "#1 — an empty (0-byte) audio/wav upload should be rejected 400/422, but the handler "
    "reaches state['learning_profile'] = student.profile first -> 500"
)
async def test_km_api_084_voice_chat_empty_file(client, student_factory, auth_headers) -> None:  # type: ignore[no-untyped-def]
    _st, tok = await student_factory()
    r = await client.post(
        "/voice/chat",
        headers=auth_headers(tok),
        files={"audio": ("a.wav", b"", "audio/wav")},
    )
    assert r.status_code in {400, 422}
