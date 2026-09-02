"""Pydantic schemas for /content and /exercise endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConceptOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    difficulty_level: str = "medium"

    class Config:
        from_attributes = True


class LessonOut(BaseModel):
    id: uuid.UUID
    concept_id: uuid.UUID
    title: str
    body_md: str
    audio_friendly_summary: str | None = None
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
    student_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    language: str = "id"


class ContentRetrieveResponse(BaseModel):
    chunks: list[dict]
    query: str


class ExerciseGenerateRequest(BaseModel):
    student_id: uuid.UUID
    concept_id: uuid.UUID | None = None
    n_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard"] | None = None


class ExerciseGenerateResponse(BaseModel):
    exercises: list[dict]
    generated_at: datetime
