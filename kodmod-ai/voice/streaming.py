"""
KODMOD AI — Voice Streaming Utilities
=====================================

Houses the helpers that the WebSocket route needs:

- `StreamingSTT`:    incremental transcription with partial-result emission.
                     Wraps faster-whisper for chunked audio (≈400ms windows).
- `stream_tts()`:    async generator yielding small audio frames so the
                     client can begin playback before the full response
                     finishes — critical for low-latency voice UX.
- `save_upload()`:   persist a multipart upload to AUDIO_DIR.
- `fetch_audio()`:   read an audio file by URL/path back into bytes.

These helpers are intentionally backend-agnostic: the actual STT/TTS
backends live in `voice/stt.py` and `voice/tts.py` and are selected via
`settings.STT_BACKEND` / `settings.TTS_BACKEND`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid
from collections import deque
from pathlib import Path
from typing import AsyncIterator, Deque, Optional

from config.settings import settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- file --
async def save_upload(upload_file, dest_dir: Optional[Path] = None) -> Path:
    """
    Save a Starlette/FastAPI UploadFile to disk and return the path.
    Uses streaming reads to avoid materialising large files in memory.
    """
    dest = dest_dir or settings.UPLOAD_DIR
    dest.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload_file.filename or "audio.wav").suffix or ".wav"
    out_path = dest / f"{uuid.uuid4().hex}{suffix}"

    chunk_size = 1 << 20  # 1 MiB
    total = 0
    with open(out_path, "wb") as f:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.MAX_AUDIO_SECONDS * 64_000:  # ~64 kB/s safety upper bound
                # We can't know exact duration without decoding; this is a coarse cap.
                logger.warning("Upload exceeded soft byte cap; truncating")
                break
            f.write(chunk)
    logger.info("Saved upload to %s (%d bytes)", out_path, total)
    return out_path


async def fetch_audio(path_or_url: str) -> bytes:
    """Read audio bytes for sending over WS or replaying."""
    if path_or_url.startswith(("http://", "https://")):
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(path_or_url)
            r.raise_for_status()
            return r.content
    p = Path(path_or_url)
    if not p.exists():
        raise FileNotFoundError(path_or_url)
    return p.read_bytes()


# ------------------------------------------------------------- streaming STT --
class StreamingSTT:
    """
    Incremental STT for low-latency voice UX.

    The WS handler feeds raw PCM/Opus chunks via `feed()`. After each chunk
    we emit either a *partial* (likely-to-change) or *final* (utterance
    boundary detected) transcription. Final segments are what we send into
    LangGraph; partials are forwarded to the client for visual feedback.

    Implementation notes:
    - Uses faster-whisper with VAD-based segmentation.
    - Buffers up to ~3s of audio before re-running inference.
    - For sub-1s ultra-low latency, swap to Deepgram via STT_BACKEND.
    """

    def __init__(
        self,
        sample_rate: int = 16_000,
        language: Optional[str] = None,
        model_size: Optional[str] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.language = language or settings.STT_LANGUAGE
        self.model_size = model_size or settings.STT_MODEL
        self._buffer: Deque[bytes] = deque()
        self._buffered_bytes = 0
        self._max_buffer_bytes = sample_rate * 2 * 6  # 6 s of 16-bit mono
        self._lock = asyncio.Lock()
        self._closed = False
        self._final_segments: list[str] = []
        self._model = None
        self._init_lock = asyncio.Lock()

    async def _ensure_model(self):
        if self._model is not None:
            return
        async with self._init_lock:
            if self._model is not None:
                return
            backend = settings.STT_BACKEND
            if backend == "faster-whisper":
                from faster_whisper import WhisperModel

                device = settings.STT_DEVICE
                if device == "auto":
                    try:
                        import torch  # type: ignore

                        device = "cuda" if torch.cuda.is_available() else "cpu"
                    except ImportError:
                        device = "cpu"
                compute_type = settings.STT_COMPUTE_TYPE if device == "cuda" else "int8"
                logger.info(
                    "Loading faster-whisper model=%s device=%s compute=%s",
                    self.model_size, device, compute_type,
                )
                self._model = WhisperModel(self.model_size, device=device, compute_type=compute_type)
            else:
                # Other backends are wrapped at request boundary in voice/stt.py.
                # For streaming, we lazily fall back to a single-shot transcribe.
                self._model = "external"

    async def feed(self, chunk: bytes) -> dict:
        """
        Push an audio chunk; returns a dict of:
          { "partial": str | None, "final": str | None, "is_speaking": bool }
        """
        if self._closed:
            return {"partial": None, "final": None, "is_speaking": False}
        async with self._lock:
            self._buffer.append(chunk)
            self._buffered_bytes += len(chunk)

            # Crude VAD: if we've accumulated >= ~1s, attempt a partial transcription.
            if self._buffered_bytes < self.sample_rate * 2:
                return {"partial": None, "final": None, "is_speaking": True}

            audio_bytes = b"".join(self._buffer)
            # Don't drain yet — we re-transcribe the rolling window for
            # better partial accuracy. We only drain on `flush_segment()`.
            if self._buffered_bytes > self._max_buffer_bytes:
                # drop the oldest second to keep memory bounded
                drop = self.sample_rate * 2
                while self._buffer and drop > 0:
                    head = self._buffer[0]
                    if len(head) <= drop:
                        drop -= len(head)
                        self._buffered_bytes -= len(head)
                        self._buffer.popleft()
                    else:
                        self._buffer[0] = head[drop:]
                        self._buffered_bytes -= drop
                        drop = 0
                audio_bytes = b"".join(self._buffer)

        partial = await self._transcribe(audio_bytes, partial=True)
        return {"partial": partial, "final": None, "is_speaking": True}

    async def flush_segment(self) -> Optional[str]:
        """
        Mark current buffer as a finalized utterance. Drains the buffer.
        Called by the WS handler when client signals end-of-utterance
        (e.g. push-to-talk release, or VAD silence detection).
        """
        async with self._lock:
            if not self._buffer:
                return None
            audio_bytes = b"".join(self._buffer)
            self._buffer.clear()
            self._buffered_bytes = 0

        text = await self._transcribe(audio_bytes, partial=False)
        if text:
            self._final_segments.append(text)
        return text

    async def close(self) -> Optional[str]:
        """Final flush and tear down."""
        self._closed = True
        return await self.flush_segment()

    async def _transcribe(self, audio_bytes: bytes, partial: bool) -> Optional[str]:
        await self._ensure_model()
        if self._model is None or self._model == "external":
            # Defer to non-streaming path
            from voice.stt import transcribe_bytes

            try:
                return await transcribe_bytes(audio_bytes, language=self.language)
            except Exception as exc:  # pragma: no cover
                logger.warning("External STT failed: %s", exc)
                return None

        # faster-whisper path
        loop = asyncio.get_running_loop()

        def _run():
            try:
                import numpy as np  # type: ignore

                pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _ = self._model.transcribe(  # type: ignore[union-attr]
                    pcm,
                    language=self.language,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 400},
                    beam_size=1 if partial else 5,
                )
                return " ".join(s.text for s in segments).strip()
            except Exception as exc:  # pragma: no cover
                logger.exception("Whisper transcription error: %s", exc)
                return ""

        return await loop.run_in_executor(None, _run)


# ------------------------------------------------------------- streaming TTS --
async def stream_tts(text: str, voice: Optional[str] = None) -> AsyncIterator[bytes]:
    """
    Async-generate audio frames for the given text.
    Frames are small (≈40 ms) MP3/Opus chunks suitable for direct WS forwarding.

    Backends:
      - elevenlabs: native streaming
      - azure: native streaming via SDK
      - piper / coqui: synthesise to WAV then chunk
    """
    voice = voice or settings.TTS_VOICE
    backend = settings.TTS_BACKEND

    if backend == "elevenlabs":
        async for frame in _stream_elevenlabs(text, voice):
            yield frame
        return
    if backend == "azure":
        async for frame in _stream_azure(text, voice):
            yield frame
        return

    # Fallback: synthesise then chunk
    from voice.tts import synthesise_bytes

    audio_bytes = await synthesise_bytes(text, voice=voice)
    chunk_size = 4096
    bio = io.BytesIO(audio_bytes)
    while True:
        chunk = bio.read(chunk_size)
        if not chunk:
            break
        yield chunk
        await asyncio.sleep(0)  # yield control


async def _stream_elevenlabs(text: str, voice: str) -> AsyncIterator[bytes]:
    api_key = settings.ELEVENLABS_API_KEY
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    import httpx

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes(chunk_size=4096):
                yield chunk


async def _stream_azure(text: str, voice: str) -> AsyncIterator[bytes]:
    """Azure streaming TTS via REST (SDK alternative not used to keep deps light)."""
    api_key = settings.AZURE_TTS_KEY
    region = settings.AZURE_TTS_REGION
    if not (api_key and region):
        raise RuntimeError("AZURE_TTS_KEY / AZURE_TTS_REGION not set")
    import httpx

    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    ssml = (
        f'<speak version="1.0" xml:lang="id-ID">'
        f'<voice name="{voice}">{text}</voice></speak>'
    )
    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, data=ssml) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes(chunk_size=4096):
                yield chunk
