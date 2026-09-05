"""Pydantic schemas for /content and /exercise endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    n_concepts: int = 0
    n_documents: int = 0


class SubjectWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ConceptWrite(BaseModel):
    subject_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9-]+$")
    description: str | None = None
    difficulty_level: Literal["beginner", "easy", "medium", "hard", "expert"] = "medium"


class DocumentOut(BaseModel):
    """An uploaded curriculum file and how far its ingestion has got."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_id: uuid.UUID
    filename: str
    size_bytes: int
    status: Literal["pending", "processing", "ready", "failed"]
    n_chunks: int
    error_message: str | None = None
    created_at: datetime
    ingested_at: datetime | None = None


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
    subject_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    language: str = "id"


class ContentRetrieveResponse(BaseModel):
    chunks: list[dict]
    query: str


class ExerciseGenerateRequest(BaseModel):
    concept_id: uuid.UUID | None = None
    n_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard"] | None = None


class ExerciseGenerateResponse(BaseModel):
    exercises: list[dict]
    generated_at: datetime
