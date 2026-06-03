"""
KODMOD AI — Text-to-Speech Pipeline
====================================

Final node before the response leaves the graph. Reads `state["accessible_response"]`
(or falls back to `generated_response`) and synthesizes audio.

Backends (selected via KODMOD_TTS_BACKEND)
------------------------------------------
* `piper`     — fully offline, low-latency, surprisingly natural. Default.
* `azure`     — neural voices, SSML support, multilingual. Recommended for prod.
* `elevenlabs`— most natural, emotion-aware. Premium tier.
* `coqui`     — open-source, voice cloning capable.

Streaming
---------
For long responses, the TTS engine streams audio chunks over the WebSocket
as soon as the first sentence is synthesized. See `voice/streaming.py`.

SSML
----
The Accessibility Agent emits lightweight `<break time="..."/>` markers.
Each backend converts them to its native syntax (Azure has SSML; Piper
ignores them; ElevenLabs supports them via the `text` parameter).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from graphs.state import KODMODState

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.getenv("KODMOD_TTS_OUTPUT_DIR", "/var/lib/kodmod/audio"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

async def tts_node(state: KODMODState) -> dict[str, Any]:
    text = (
        state.get("accessible_response")
        or state.get("generated_response")
        or ""
    ).strip()

    if not text:
        return {"audio_response_path": "", "next_action": "end", "last_node": "tts"}

    voice = (
        state.get("learning_profile", {}).get("preferred_voice")
        or os.getenv("KODMOD_TTS_VOICE", "id-ID-ArdiNeural")
    )
    backend = os.getenv("KODMOD_TTS_BACKEND", "piper")

    if backend == "azure":
        path = await _azure_tts(text, voice)
    elif backend == "elevenlabs":
        path = await _elevenlabs_tts(text, voice)
    elif backend == "coqui":
        path = await _coqui_tts(text, voice)
    else:
        path = await _piper_tts(text, voice)

    log.info("TTS: %d chars → %s", len(text), path)
    return {
        "audio_response_path": str(path),
        "next_action": "end",
        "last_node": "tts",
    }


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _piper_voice(model_name: str):
    """Lazy-load a Piper voice model."""
    from piper import PiperVoice
    voices_dir = Path(os.getenv("KODMOD_PIPER_VOICES_DIR", "/opt/piper/voices"))
    return PiperVoice.load(voices_dir / f"{model_name}.onnx")


async def _piper_tts(text: str, voice: str) -> Path:
    out = OUTPUT_DIR / f"tts-{uuid4().hex}.wav"
    voice_id = voice if voice.endswith(".onnx") else "id_ID-fajri-medium"

    def _run():
        v = _piper_voice(voice_id)
        with open(out, "wb") as f:
            v.synthesize(_strip_ssml(text), f)
    await asyncio.get_running_loop().run_in_executor(None, _run)
    return out


async def _azure_tts(text: str, voice: str) -> Path:
    import azure.cognitiveservices.speech as speechsdk
    out = OUTPUT_DIR / f"tts-{uuid4().hex}.wav"
    cfg = speechsdk.SpeechConfig(
        subscription=os.environ["AZURE_SPEECH_KEY"],
        region=os.environ["AZURE_SPEECH_REGION"],
    )
    cfg.speech_synthesis_voice_name = voice
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3,
    )
    audio_cfg = speechsdk.audio.AudioOutputConfig(filename=str(out))
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=audio_cfg)
    ssml = _to_ssml(text, voice)

    def _run():
        synth.speak_ssml_async(ssml).get()
    await asyncio.get_running_loop().run_in_executor(None, _run)
    return out


async def _elevenlabs_tts(text: str, voice: str) -> Path:
    from elevenlabs.client import AsyncElevenLabs
    out = OUTPUT_DIR / f"tts-{uuid4().hex}.mp3"
    client = AsyncElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    audio_iter = client.text_to_speech.convert(
        voice_id=voice,
        text=_strip_ssml(text),
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    with open(out, "wb") as f:
        async for chunk in audio_iter:
            f.write(chunk)
    return out


async def _coqui_tts(text: str, voice: str) -> Path:
    from TTS.api import TTS
    out = OUTPUT_DIR / f"tts-{uuid4().hex}.wav"
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)
    def _run():
        tts.tts_to_file(text=_strip_ssml(text), file_path=str(out),
                        speaker_wav=voice if voice.endswith(".wav") else None,
                        language="id")
    await asyncio.get_running_loop().run_in_executor(None, _run)
    return out


# ---------------------------------------------------------------------------
# SSML helpers
# ---------------------------------------------------------------------------

_SSML_BREAK_RE = re.compile(r'<break\s+time="(\d+)(ms|s)"\s*/?\s*>', re.IGNORECASE)

def _strip_ssml(text: str) -> str:
    return _SSML_BREAK_RE.sub(" ", text).strip()


def _to_ssml(text: str, voice: str) -> str:
    body = _SSML_BREAK_RE.sub(
        lambda m: f'<break time="{m.group(1)}{m.group(2)}"/>', text
    )
    return (
        f'<speak version="1.0" xml:lang="id-ID" '
        f'xmlns="http://www.w3.org/2001/10/synthesis">'
        f'<voice name="{voice}"><prosody rate="0.95">{body}</prosody></voice>'
        f'</speak>'
    )


# ---------------------------------------------------------------------------
# Public helpers — used by tools/voice_tool.py and voice/streaming.py
# ---------------------------------------------------------------------------
from config.settings import settings  # noqa: E402  (kept here to avoid cycles)


async def synthesise_to_file(
    text: str,
    *,
    voice: str | None = None,
    rate: float = 1.0,
) -> Path:
    """Synthesise text to an audio file and return its path."""
    voice = voice or settings.TTS_VOICE
    backend = settings.TTS_BACKEND
    plain = _strip_ssml(text)
    if backend == "piper":
        return await _piper_tts(plain, voice)
    if backend == "azure":
        return await _azure_tts(text, voice)
    if backend == "elevenlabs":
        return await _elevenlabs_tts(plain, voice)
    if backend == "coqui":
        return await _coqui_tts(plain, voice)
    raise ValueError(f"Unknown TTS_BACKEND: {backend}")


async def synthesise_bytes(
    text: str,
    *,
    voice: str | None = None,
    rate: float = 1.0,
) -> bytes:
    """Synthesise text and return raw audio bytes (mp3/wav depending on backend)."""
    path = await synthesise_to_file(text, voice=voice, rate=rate)
    try:
        return Path(path).read_bytes()
    finally:
        # Don't delete — caller may want the file. Cleanup happens via AUDIO_DIR rotation.
        pass
