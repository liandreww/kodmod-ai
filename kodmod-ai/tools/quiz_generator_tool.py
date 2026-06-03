"""
KODMOD AI — Quiz Generator Tool
===============================

Tool wrapper around the problem-generation logic in
`agents.problem_generator`. Lets agents (e.g. a Tutoring Agent that
notices the student is ready for a self-check) request a fresh batch
of adaptive questions without going through the full graph routing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GenerateQuizInput(BaseModel):
    student_id: str
    concept_id: Optional[str] = None
    n_questions: int = Field(default=5, ge=1, le=15)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    topic_hint: Optional[str] = None


async def generate_quiz(
    student_id: str,
    *,
    concept_id: Optional[str] = None,
    n_questions: int = 5,
    difficulty: Optional[str] = None,
    topic_hint: Optional[str] = None,
) -> dict:
    """
    Returns a dict with:
        questions: list[QuizQuestion]
        difficulty: chosen difficulty
        rationale: short note on why these questions were selected
    """
    # Lazy import to avoid circular ref with agents -> tools -> agents.
    from agents.problem_generator import generate_questions_for_student

    questions = await generate_questions_for_student(
        student_id=uuid.UUID(student_id),
        concept_id=uuid.UUID(concept_id) if concept_id else None,
        n=n_questions,
        difficulty_hint=difficulty,
        topic_hint=topic_hint,
    )
    return {
        "questions": questions,
        "difficulty": difficulty or "adaptive",
        "rationale": (
            f"Generated {len(questions)} adaptive question(s) "
            f"for student {student_id[:8]} on concept "
            f"{(concept_id[:8] if concept_id else 'auto-selected')}."
        ),
    }


def get_quiz_generator_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=generate_quiz,
        name="generate_adaptive_quiz",
        description=(
            "Generate an adaptive quiz tailored to a specific student's mastery profile. "
            "Use when the student wants a self-check, or when the tutor decides assessment "
            "would aid retention."
        ),
        args_schema=GenerateQuizInput,
    )
