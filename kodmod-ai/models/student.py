"""Pydantic schemas for /student endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StudentBase(BaseModel):
    full_name: str
    email: Optional[str] = None
    grade_level: Optional[str] = None
    accessibility_profile: str = "blind"
    preferred_language: str = "id"


class StudentCreate(StudentBase):
    voice_settings: dict = Field(default_factory=dict)


class StudentOut(StudentBase):
    id: uuid.UUID
    voice_settings: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StudentProfileOut(StudentOut):
    """Extended profile including aggregated learning state."""

    overall_mastery: float = 0.0
    weak_concepts: list[str] = Field(default_factory=list)
    strong_concepts: list[str] = Field(default_factory=list)
    streak_days: int = 0
    last_active_at: Optional[datetime] = None
