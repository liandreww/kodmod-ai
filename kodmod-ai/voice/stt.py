"""
KODMOD AI — Speech-to-Text Pipeline
====================================

LangGraph entry node. Reads `state["audio_input_path"]` (an S3/MinIO/local
URI containing the inbound audio chunk) and returns transcribed text plus a
detected language code.

Backends
--------
* `faster-whisper` — default for self-hosted, low-latency, on-prem deployments.
* `openai-whisper-1` — managed fallback when KODMOD_STT_BACKEND=openai.
* `deepgram` — live streaming transcription for the WebSocket path.

Streaming
---------
For partial transcripts during live voice input, see
`voice/streaming.py::StreamingSTT` which emits incremental results to the
WebSocket independently of the LangGraph turn boundary.
"""
from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from typing import Any

from graphs.state import KODMODState
from config.settings import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _faster_whisper_model():
    from faster_whisper import WhisperModel
    size = os.getenv("KODMOD_WHISPER_SIZE", "large-v3")
    device = os.getenv("KODMOD_WHISPER_DEVICE", "cuda")
    compute = os.getenv("KODMOD_WHISPER_COMPUTE", "float16")
    log.info("Loading faster-whisper %s on %s/%s", size, device, compute)
    return WhisperModel(size, device=device, compute_type=compute)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

async def stt_node(state: KODMODState) -> dict[str, Any]:
    """Transcribe state['audio_input_path'] to state['transcribed_text']."""
    path = state.get("audio_input_path", "")
    if not path:
        # Allow text-only invocation (e.g. teacher dashboard chat)
        text = state.get("user_input", "")
        return {
            "transcribed_text": text,
            "detected_language": state.get("detected_language", "id"),
            "next_action": "route_intent",
            "last_node": "stt",
        }

    backend = os.getenv("KODMOD_STT_BACKEND", "faster-whisper")
    if backend == "openai":
        text, lang = await _openai_stt(path)
    elif backend == "deepgram":
        text, lang = await _deepgram_stt(path)
    else:
        text, lang = await _fw_stt(path)

    log.info("STT: %d chars (lang=%s)", len(text), lang)
    return {
        "transcribed_text": text,
        "detected_language": lang,
        "next_action": "route_intent",
        "last_node": "stt",
    }


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

async def _fw_stt(path: str) -> tuple[str, str]:
    model = _faster_whisper_model()

    def _run() -> tuple[str, str]:
        local_path = _ensure_local(path)
        segments, info = model.transcribe(
            local_path,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language

    return await asyncio.get_running_loop().run_in_executor(None, _run)


async def _openai_stt(path: str) -> tuple[str, str]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI()
    local_path = _ensure_local(path)
    with open(local_path, "rb") as f:
        result = await client.audio.transcriptions.create(
            model="whisper-1", file=f, response_format="verbose_json",
        )
    return result.text, result.language


async def _deepgram_stt(path: str) -> tuple[str, str]:
    """Used mostly via the streaming path, but also exposed here for batch."""
    from deepgram import DeepgramClient, PrerecordedOptions
    dg = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    local_path = _ensure_local(path)
    with open(local_path, "rb") as f:
        payload = {"buffer": f.read()}
    options = PrerecordedOptions(
        model="nova-2", language="multi", smart_format=True, punctuate=True,
    )
    resp = await dg.listen.asyncrest.v("1").transcribe_file(payload, options)
    transcript = resp["results"]["channels"][0]["alternatives"][0]["transcript"]
    detected = resp["results"]["channels"][0]["detected_language"]
    return transcript, detected


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _ensure_local(uri: str) -> str:
    """Download remote URIs to a temp file and return a local path."""
    if uri.startswith(("http://", "https://", "s3://", "minio://")):
        from voice.streaming import fetch_audio
        return fetch_audio(uri)
    return uri


# ---------------------------------------------------------------------------
# Public helpers — used by tools/voice_tool.py and voice/streaming.py
# ---------------------------------------------------------------------------
async def transcribe_path(path, *, language: str | None = None) -> str:
    """Transcribe an audio file at the given path. Backend chosen by settings."""
    from pathlib import Path as _Path

    p = str(path) if isinstance(path, _Path) else path
    backend = settings.STT_BACKEND
    if backend == "faster-whisper":
        text, _lang = await _fw_stt(p)
    elif backend == "openai-whisper":
        text, _lang = await _openai_stt(p)
    elif backend == "deepgram":
        text, _lang = await _deepgram_stt(p)
    else:  # pragma: no cover
        raise ValueError(f"Unknown STT_BACKEND: {backend}")
    return text


async def transcribe_bytes(audio_bytes: bytes, *, language: str | None = None) -> str:
    """
    Transcribe in-memory audio bytes. Writes to a temp file for backends
    that need a path; for faster-whisper we go straight through the model.
    """
    import tempfile

    suffix = ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        return await transcribe_path(tmp_path, language=language)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
