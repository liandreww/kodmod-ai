"""
KODMOD AI — Chat Turn Service
=============================

The shared middle of a conversation turn, so the WebSocket and the REST
fallback behave identically and only differ in how they deliver the answer.

Responsibilities:

* Open or resume a `LearningSession`, naming it after the student's opening
  question so the history sidebar is scannable.
* Assemble the graph's `KODMODState` for one turn.
* Record both sides of the turn in `interaction_logs`, which is what the
  teacher's transcript view reads.

The graph itself is invoked by the caller: the WebSocket streams events, the
REST route awaits a single result, and neither wants the other's plumbing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from database.models import LearningSession, User
from database.session import async_session
from graphs.state import KODMODState, build_learning_profile, initial_state

log = logging.getLogger(__name__)

TITLE_MAX_CHARS = 60


def derive_title(text: str) -> str:
    """Name a session after its opening question, trimmed at a word boundary."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned or "Sesi baru"
    head = cleaned[:TITLE_MAX_CHARS].rsplit(" ", 1)[0]
    return (head or cleaned[:TITLE_MAX_CHARS]) + "..."


async def open_session(
    *,
    student_id: uuid.UUID,
    session_id: uuid.UUID | None,
    subject_id: uuid.UUID | None,
    first_text: str,
) -> uuid.UUID:
    """Resume the named session, or start one. Returns the id to use as thread_id.

    A `session_id` the student does not own is treated as absent rather than as
    an error: it starts a fresh session instead of leaking whether that id exists.
    """
    async with async_session() as session:
        if session_id is not None:
            existing = (
                await session.execute(
                    select(LearningSession).where(
                        LearningSession.id == session_id,
                        LearningSession.student_id == student_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if subject_id is not None and existing.subject_id != subject_id:
                    existing.subject_id = subject_id
                    await session.commit()
                return existing.id

        row = LearningSession(
            id=session_id or uuid.uuid4(),
            student_id=student_id,
            subject_id=subject_id,
            title=derive_title(first_text),
            mode="tutoring",
        )
        session.add(row)
        await session.commit()
        return row.id


async def build_turn_state(
    *,
    student: User,
    session_id: uuid.UUID,
    text: str,
    subject_id: uuid.UUID | None,
) -> KODMODState:
    """A fresh state for one turn, pre-loaded with the learner's mastery."""
    from analytics.student_model import StudentModel

    state = initial_state(
        session_id=str(session_id),
        student_id=str(student.id),
        user_input=text,
        subject_id=str(subject_id) if subject_id else None,
    )
    state["learning_profile"] = build_learning_profile(student)
    try:
        model = await StudentModel.load(str(student.id))
        state["mastery_scores"] = await model.mastery_scores()
    except Exception:  # pragma: no cover - a cold mastery table must not block a turn
        log.warning("Could not load mastery for %s", student.id, exc_info=True)
    return state


_MODE_BY_INTENT = {
    "quiz": "quiz",
    "exercise_request": "quiz",
    "analytics": "analytics",
}


async def update_session_mode(session_id: uuid.UUID, intent: str | None) -> None:
    """Keep ``learning_sessions.mode`` in sync with the latest turn's intent.

    Never raises into the request path: a lost mode update must not break a
    turn, and callers already treat ``log_turn`` the same way.
    """
    mode = _MODE_BY_INTENT.get(intent or "", "tutoring")
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(LearningSession).where(LearningSession.id == session_id)
                )
            ).scalar_one_or_none()
            if row is not None and row.mode != mode:
                row.mode = mode
                await session.commit()
    except Exception:  # pragma: no cover - a lost mode update must not break a turn
        log.warning("Could not update mode for session %s", session_id, exc_info=True)


async def log_turn(
    session_id: uuid.UUID,
    *,
    role: str,
    text: str,
    intent: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Append one turn to the transcript. Never raises into the request path."""
    from memory.long_term import log_interaction

    try:
        await log_interaction(
            session_id, role=role, text=text, intent=intent, latency_ms=latency_ms
        )
    except Exception:  # pragma: no cover - a lost log line must not break the reply
        log.warning("Could not log %s turn for session %s", role, session_id, exc_info=True)


async def close_session(session_id: uuid.UUID, student_id: uuid.UUID) -> bool:
    """Mark a session ended. Returns False if it is not this student's session."""
    async with async_session() as session:
        row = (
            await session.execute(
                select(LearningSession).where(
                    LearningSession.id == session_id,
                    LearningSession.student_id == student_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.ended_at = datetime.now(UTC)
        await session.commit()
        return True


def reply_text(final: dict) -> str:
    """The text to show the student: the accessibility pass, or the raw answer."""
    return final.get("accessible_response") or final.get("generated_response") or ""


def sources(final: dict) -> list[dict]:
    """Which curriculum chunks grounded this answer, for the sources disclosure."""
    seen: dict[str, dict] = {}
    for doc in final.get("retrieved_docs") or []:
        source = doc.get("source") or ""
        if source and source not in seen:
            seen[source] = {
                "source": source,
                "section_title": doc.get("section_title"),
                "score": round(float(doc.get("rerank_score") or doc.get("score") or 0.0), 3),
            }
    return list(seen.values())
