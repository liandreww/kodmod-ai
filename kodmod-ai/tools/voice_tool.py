"""
KODMOD AI — Voice Tool
======================

Unified entrypoint for STT and TTS. Mostly used by tools/utility callers
that need direct voice processing without going through the WebSocket
pipeline (e.g. a teacher uploading recorded student answers in batch).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from voice.stt import transcribe_path
from voice.tts import synthesise_to_file

logger = logging.getLogger(__name__)


class TranscribeInput(BaseModel):
    audio_path: str = Field(..., description="Filesystem path to audio file")
    language: str = "id"


async def transcribe_audio(audio_path: str, *, language: str = "id") -> dict:
    text = await transcribe_path(Path(audio_path), language=language)
    return {"text": text, "language": language}


def get_transcribe_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=transcribe_audio,
        name="transcribe_audio",
        description="Transcribe an audio file to text using the configured STT backend.",
        args_schema=TranscribeInput,
    )


class SynthesizeInput(BaseModel):
    text: str
    voice: Optional[str] = None
    rate: float = 1.0


async def synthesize_speech(
    text: str, *, voice: Optional[str] = None, rate: float = 1.0
) -> dict:
    out_path = await synthesise_to_file(text, voice=voice, rate=rate)
    return {"audio_path": str(out_path)}


def get_synthesize_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=synthesize_speech,
        name="synthesize_speech",
        description=(
            "Convert text to speech using the configured TTS backend and return the path "
            "to the generated audio file."
        ),
        args_schema=SynthesizeInput,
    )
