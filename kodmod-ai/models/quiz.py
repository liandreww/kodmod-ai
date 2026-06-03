"""Pydantic schemas for /quiz endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class QuizStartRequest(BaseModel):
    student_id: uuid.UUID
    concept_id: Optional[uuid.UUID] = None
    n_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    language: Literal["id", "en"] = "id"


class QuizQuestionOut(BaseModel):
    question_id: str
    order_index: int
    question: str
    question_type: Literal["mcq", "spoken", "explain", "reasoning", "step_by_step"]
    options: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    audio_url: Optional[str] = None  # pre-rendered TTS for the question


class QuizStartResponse(BaseModel):
    quiz_session_id: uuid.UUID
    first_question: QuizQuestionOut
    total_questions: int


class QuizSubmitRequest(BaseModel):
    quiz_session_id: uuid.UUID
    question_id: str
    student_answer: str
    response_latency_ms: Optional[int] = None
    transcribed_from_audio: bool = False


class QuizSubmitResponse(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    is_correct: bool
    feedback: str
    spoken_feedback_audio_url: Optional[str] = None
    next_question: Optional[QuizQuestionOut] = None
    quiz_complete: bool = False
    final_summary: Optional[str] = None
    final_summary_audio_url: Optional[str] = None
    cumulative_score: float = 0.0


class QuizSessionOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime]
    total_questions: int
    correct_count: int
    final_score: Optional[float]
    status: str

    class Config:
        from_attributes = True
