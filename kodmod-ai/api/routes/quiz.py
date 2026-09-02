"""
KODMOD AI — Quiz REST Routes
=============================

For clients that want fine-grained control over quiz sessions outside the
voice WebSocket (e.g. teacher dashboards previewing a quiz, or accessibility
tools that prefer text submission).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from api.dependencies import current_student
from config.settings import settings
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
        quiz_session_id=final.get("quiz_session_id", ""),
        first_question=final.get("quiz_question", {}),
        total_questions=len(final.get("quiz_questions", [])),
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
    thread_id = str(body.quiz_session_id)
    state = {
        "session_id": thread_id,
        "student_id": student.id,
        "student_answer": body.student_answer,
        "user_input": body.student_answer,
        "intent": "quiz",
    }
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Resume the graph from its last checkpoint, injecting the new answer
    final = await graph.ainvoke(state, config=config)

    score = final.get("quiz_score", 0.0)
    answered = final.get("current_question_index", 0) + 1
    total = len(final.get("quiz_questions", []))

    return QuizSubmitResponse(
        score=score,
        is_correct=score >= settings.QUIZ_PASS_THRESHOLD,
        feedback=final.get("generated_response", ""),
        spoken_feedback_audio_url=final.get("audio_response_path", "") or None,
        cumulative_score=final.get("cumulative_quiz_score", 0.0),
        quiz_complete=answered >= total,
        next_question=final.get("quiz_question") if answered < total else None,
    )


# ---------------------------------------------------------------------------


async def _load_mastery(student_id: str) -> dict[str, float]:
    from analytics.student_model import StudentModel

    model = await StudentModel.load(student_id)
    return await model.mastery_scores()
