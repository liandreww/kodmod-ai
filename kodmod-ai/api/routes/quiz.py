"""
KODMOD AI — Quiz REST Routes
=============================

For clients that want fine-grained control over quiz sessions outside the
voice WebSocket (e.g. teacher dashboards previewing a quiz, or accessibility
tools that prefer text submission).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select

from api.dependencies import current_student
from config.settings import settings
from database.models import QuizAttempt, QuizQuestion, QuizSession, Student
from database.session import async_session
from graphs.state import build_learning_profile, initial_state
from models.quiz import (
    QuizQuestionOut,
    QuizStartRequest,
    QuizStartResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
)

log = logging.getLogger(__name__)
router = APIRouter()


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _to_question_out(q: dict[str, Any] | None, idx: int) -> QuizQuestionOut:
    """Map the internal ``QuizQuestion`` state dict onto the API schema."""
    q = q or {}
    return QuizQuestionOut(
        question_id=str(q.get("question_id", "")),
        order_index=idx,
        question=q.get("text") or q.get("question") or "",
        question_type=q.get("type") or q.get("question_type") or "spoken",
        options=list(q.get("options") or []),
        difficulty=str(q.get("difficulty") or "medium"),
        audio_url=q.get("audio_url"),
    )


@router.post("/start", response_model=QuizStartResponse)
async def start_quiz(
    request: Request,
    body: QuizStartRequest,
    student: Student = Depends(current_student),
) -> QuizStartResponse:
    """
    Start a new quiz session by invoking the problem generator.
    Returns the first question (text + audio URI).
    """
    if body.student_id != student.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mismatched student_id")

    sid = str(uuid4())
    state = initial_state(session_id=sid, student_id=str(student.id))
    state["intent"] = "quiz"
    state["current_concept_id"] = str(body.concept_id) if body.concept_id else ""
    state["current_difficulty"] = body.difficulty or "medium"
    state["quiz_n_questions"] = body.n_questions
    state["mastery_scores"] = await _load_mastery(str(student.id))
    state["learning_profile"] = build_learning_profile(student)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": sid}}
    final = await graph.ainvoke(state, config=config)

    questions = final.get("quiz_questions") or []
    if not questions:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "quiz generation failed")

    # Persist the session + its questions so the analytics rollup
    # (quiz_attempts ⋈ quiz_sessions) can later count this quiz. `sid` doubles
    # as the checkpoint thread id and the QuizSession primary key.
    try:
        async with async_session() as s:
            s.add(
                QuizSession(
                    id=UUID(sid),
                    student_id=student.id,
                    concept_id=body.concept_id,
                    total_questions=len(questions),
                    status="in_progress",
                )
            )
            # Flush the session row before the questions so their FK resolves
            # (no ORM relationship links the two, so the unit of work would
            # otherwise not order the inserts).
            await s.flush()
            for i, q in enumerate(questions):
                qid = _uuid_or_none(q.get("question_id")) or uuid4()
                s.add(
                    QuizQuestion(
                        id=qid,
                        quiz_session_id=UUID(sid),
                        order_index=i,
                        question=q.get("text") or q.get("question") or "",
                        question_type=str(q.get("type") or q.get("question_type") or "spoken"),
                        options=list(q.get("options") or []),
                        correct_answer=str(q.get("expected_answer") or ""),
                        concept_id=_uuid_or_none(q.get("concept_id")),
                        difficulty=str(q.get("difficulty") or "medium"),
                    )
                )
    except Exception:  # pragma: no cover - persistence must not break quiz start
        log.warning("Could not persist quiz session %s", sid, exc_info=True)

    # The `sid` — not the internal `quiz-xxxx` label — is the checkpoint thread id
    # and the short-term-memory key, so it must be what the client sends back to
    # /quiz/submit.
    return QuizStartResponse(
        quiz_session_id=UUID(sid),
        first_question=_to_question_out(final.get("quiz_question") or questions[0], 0),
        total_questions=len(questions),
    )


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_answer(
    request: Request,
    body: QuizSubmitRequest,
    student: Student = Depends(current_student),
) -> QuizSubmitResponse:
    """
    Submit one answer to the current quiz question. The graph re-enters at
    the scoring node thanks to LangGraph state persistence.
    """
    thread_id = str(body.quiz_session_id)
    state = {
        "session_id": thread_id,
        "student_id": str(student.id),
        "student_answer": body.student_answer,
        "user_input": body.student_answer,
        "intent": "quiz",
    }
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Resume the graph from its last checkpoint, injecting the new answer
    final = await graph.ainvoke(state, config=config)

    # If the graph paused on the reflection interrupt but the quiz is already
    # exhausted, drive it through analytics → recommendation → accessibility.
    try:
        snapshot = await graph.aget_state(config)
        pending = bool(getattr(snapshot, "next", ()))
    except Exception:  # pragma: no cover - best effort
        pending = False
    total = len(final.get("quiz_questions", []))
    answered = final.get("current_question_index", 0)
    if pending and total and answered >= total:
        final = await graph.ainvoke(None, config=config)
        total = len(final.get("quiz_questions", []))
        answered = final.get("current_question_index", 0)

    score = final.get("quiz_score", 0.0)
    cumulative = final.get("cumulative_quiz_score", 0.0)
    quiz_complete = bool(total) and answered >= total

    # Persist any newly-scored attempts so the analytics rollup can count them.
    # `final["quiz_attempts"]` is the checkpointed list — it grows by one per
    # submit; we only write the rows we haven't written yet.
    session_uuid = _uuid_or_none(thread_id)
    attempts = final.get("quiz_attempts", []) or []
    if session_uuid and attempts:
        try:
            async with async_session() as s:
                qs = await s.get(QuizSession, session_uuid)
                if qs is not None:
                    n_written = (
                        await s.execute(
                            select(func.count())
                            .select_from(QuizAttempt)
                            .where(QuizAttempt.quiz_session_id == session_uuid)
                        )
                    ).scalar_one()
                    for idx in range(n_written, len(attempts)):
                        att = attempts[idx]
                        qqid = _uuid_or_none(att.get("question_id"))
                        if qqid is None:
                            qqid = (
                                await s.execute(
                                    select(QuizQuestion.id).where(
                                        QuizQuestion.quiz_session_id == session_uuid,
                                        QuizQuestion.order_index == idx,
                                    )
                                )
                            ).scalar_one_or_none()
                        if qqid is None:
                            continue
                        s.add(
                            QuizAttempt(
                                quiz_session_id=session_uuid,
                                quiz_question_id=qqid,
                                student_answer=body.student_answer,
                                score=float(att.get("score", 0.0)),
                                is_correct=bool(
                                    att.get("is_correct", score >= settings.QUIZ_PASS_THRESHOLD)
                                ),
                                confidence=float(att.get("confidence", 0.0)),
                                feedback=att.get("feedback"),
                                response_latency_ms=body.response_latency_ms,
                            )
                        )
                    if quiz_complete:
                        qs.status = "completed"
                        qs.ended_at = datetime.utcnow()
                        qs.final_score = cumulative
                        qs.correct_count = sum(1 for a in attempts if a.get("is_correct"))
        except Exception:  # pragma: no cover - persistence must not break submit
            log.warning("Could not persist quiz attempt for %s", thread_id, exc_info=True)

    final_summary = None
    if quiz_complete:
        final_summary = (
            final.get("generated_response")
            or final.get("accessible_response")
            or f"Kuis selesai. Skor kamu {cumulative:.0%}."
        )

    return QuizSubmitResponse(
        score=score,
        is_correct=score >= settings.QUIZ_PASS_THRESHOLD,
        feedback=final.get("generated_response", ""),
        spoken_feedback_audio_url=final.get("audio_response_path", "") or None,
        cumulative_score=cumulative,
        quiz_complete=quiz_complete,
        final_summary=final_summary,
        final_summary_audio_url=(final.get("audio_response_path") or None)
        if quiz_complete
        else None,
        next_question=(
            _to_question_out(final.get("quiz_question"), answered)
            if not quiz_complete and final.get("quiz_question")
            else None
        ),
    )


# ---------------------------------------------------------------------------


async def _load_mastery(student_id: str) -> dict[str, float]:
    from analytics.student_model import StudentModel

    model = await StudentModel.load(student_id)
    return await model.mastery_scores()
