"""Pydantic schemas for learning sessions."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionStartRequest(BaseModel):
    student_id: uuid.UUID
    mode: str = "tutoring"  # tutoring | quiz | mixed


class SessionOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    mode: str
    summary: Optional[str] = None

    class Config:
        from_attributes = True


class VoiceChatRequest(BaseModel):
    """Text fallback for /voice/text — when audio upload is not feasible."""

    student_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    text: str
    language: str = "id"


class VoiceChatResponse(BaseModel):
    session_id: uuid.UUID
    intent: str
    response_text: str
    response_audio_url: Optional[str] = None
    latency_ms: int = 0
    metadata: dict = Field(default_factory=dict)
