"""
KODMOD AI — Quiz REST Routes
=============================

For clients that want fine-grained control over quiz sessions outside the
voice WebSocket (e.g. teacher dashboards previewing a quiz, or accessibility
tools that prefer text submission).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from api.dependencies import current_student
from graphs.state import initial_state
from models.quiz import QuizStartRequest, QuizStartResponse, QuizSubmitRequest, QuizSubmitResponse
from models.student import StudentOut

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/start", response_model=QuizStartResponse)
async def start_quiz(
    request: Request,
    body: QuizStartRequest,
    student: StudentOut = Depends(current_student),
):
    """
    Start a new quiz session by invoking the problem generator.
    Returns the first question (text + audio URI).
    """
    sid = str(uuid4())
    state = initial_state(session_id=sid, student_id=student.id)
    state["intent"] = "quiz"
    state["current_concept_id"] = body.concept_id
    state["current_difficulty"] = body.difficulty or "medium"
    state["mastery_scores"] = await _load_mastery(student.id)
    state["learning_profile"] = student.profile

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": sid}}
    final = await graph.ainvoke(state, config=config)

    return QuizStartResponse(
        session_id=sid,
        quiz_session_id=final.get("quiz_session_id", ""),
        total_questions=len(final.get("quiz_questions", [])),
        first_question=final.get("quiz_question", {}),
        question_audio_uri=final.get("audio_response_path", ""),
    )


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_answer(
    request: Request,
    body: QuizSubmitRequest,
    student: StudentOut = Depends(current_student),
):
    """
    Submit one answer to the current quiz question. The graph re-enters at
    the scoring node thanks to LangGraph state persistence.
    """
    state = {
        "session_id": body.session_id,
        "student_id": student.id,
        "student_answer": body.answer_text,
        "user_input": body.answer_text,
        "intent": "quiz",
    }
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": body.session_id}}

    # Resume the graph from its last checkpoint, injecting the new answer
    final = await graph.ainvoke(state, config=config)

    return QuizSubmitResponse(
        session_id=body.session_id,
        score=final.get("quiz_score", 0.0),
        cumulative_score=final.get("cumulative_quiz_score", 0.0),
        feedback_text=final.get("generated_response", ""),
        feedback_audio_uri=final.get("audio_response_path", ""),
        is_session_complete=(
            final.get("current_question_index", 0) + 1
            >= len(final.get("quiz_questions", []))
        ),
        next_question=final.get("quiz_question") if final.get("current_question_index", 0) + 1 < len(final.get("quiz_questions", [])) else None,
    )


# ---------------------------------------------------------------------------

async def _load_mastery(student_id: str) -> dict[str, float]:
    from analytics.student_model import StudentModel
    return await StudentModel.load(student_id).mastery_scores()
