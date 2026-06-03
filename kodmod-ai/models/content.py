"""Pydantic schemas for /content and /exercise endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConceptOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    difficulty_level: str = "medium"

    class Config:
        from_attributes = True


class LessonOut(BaseModel):
    id: uuid.UUID
    concept_id: uuid.UUID
    title: str
    body_md: str
    audio_friendly_summary: Optional[str] = None
    estimated_minutes: int = 10

    class Config:
        from_attributes = True


class ExerciseOut(BaseModel):
    id: uuid.UUID
    concept_id: uuid.UUID
    question: str
    question_type: str
    options: list[str] = Field(default_factory=list)
    difficulty: str

    class Config:
        from_attributes = True


class ContentRetrieveRequest(BaseModel):
    query: str
    student_id: Optional[uuid.UUID] = None
    top_k: int = Field(default=5, ge=1, le=20)
    language: str = "id"


class ContentRetrieveResponse(BaseModel):
    chunks: list[dict]
    query: str


class ExerciseGenerateRequest(BaseModel):
    student_id: uuid.UUID
    concept_id: Optional[uuid.UUID] = None
    n_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None


class ExerciseGenerateResponse(BaseModel):
    exercises: list[dict]
    generated_at: datetime
