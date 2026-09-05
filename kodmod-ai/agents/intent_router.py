"""
KODMOD AI — Intent Router Agent
================================

Maps the student's transcribed utterance to one of the discrete intents that
the rest of the graph knows how to handle.

This is the agent behind the 'What do you want?' diamond in the
Practices & Tutoring diagram.

Design choices
--------------
* We use a small, fast LLM (configurable) for classification — Claude Haiku /
  Llama-3-8B / GPT-4o-mini are all good fits.
* The output is a strict JSON object validated with Pydantic; if validation
  fails we fall back to "tutoring" (the safest, most helpful default for an
  educational assistant).
* When the system is mid-quiz (quiz_session_id present and we're awaiting an
  answer), we short-circuit and force `intent="quiz"` so the student's reply
  is treated as a quiz answer, not a new tutoring question.
"""

from __future__ import annotations

import json
import logging
from typing import cast

from pydantic import BaseModel, Field, ValidationError

from graphs.state import Intent, KODMODState
from tools.llm_client import get_router_llm, language_instruction

log = logging.getLogger(__name__)


class IntentDecision(BaseModel):
    intent: Intent = Field(description="One of the predefined intents")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="One-sentence explanation")
    detected_emotion: str = Field(default="neutral")
    topic: str = Field(
        default="", description="Subject/topic named by the student, if any (else empty)"
    )


SYSTEM_PROMPT = """\
You are the Intent Router for KODMOD AI, a voice-first learning assistant for
visually impaired students. Classify the student's spoken utterance into ONE
intent from this list:

- tutoring        : asks for explanation, help understanding, examples
- quiz            : asks to start a quiz / answers a quiz question
- analytics       : asks about progress, scores, weak areas
- clarification   : asks to repeat or explain differently
- exercise_request: asks for practice problems
- help            : asks how to use the system
- navigation      : 'next topic', 'go back', 'pause'
- repeat          : 'say that again', 'repeat'
- stop            : 'stop', 'end session', 'goodbye'
- unknown         : unclear / off-topic

Also detect emotional state: neutral | engaged | confused | frustrated |
fatigued | motivated.

When the intent is quiz, exercise_request, or tutoring, also extract the
subject/topic the student named, in their own words (e.g. "pecahan",
"tata surya"). Leave it empty if no topic is named (e.g. "lanjutkan",
"ulangi soal terakhir").

Return ONLY a JSON object, no prose:
{"intent": "...", "confidence": 0.0-1.0, "reasoning": "...",
 "detected_emotion": "...", "topic": "..."}
"""


async def intent_router_node(state: KODMODState) -> dict:
    """LangGraph node — the graph entry point, before any cluster logic."""
    text = state.get("user_input", "")
    if not text.strip():
        # No utterance to classify (e.g. a REST entrypoint that drives the graph
        # directly). Honour a concrete intent the caller already set instead of
        # clobbering it with "unknown".
        preset = state.get("intent") or "unknown"
        return {
            "intent": preset,
            "intent_confidence": 0.0 if preset == "unknown" else 0.9,
            "next_action": "route_intent",
            "last_node": "intent_router",
        }

    # --- Hard short-circuit: if we're mid-quiz, the utterance IS the answer.
    # The graph re-enters at `intent_router` with a fresh state every turn, so
    # the quiz progress may only exist in short-term memory — rehydrate it here.
    quiz_session_id = state.get("quiz_session_id")
    quiz_questions = state.get("quiz_questions") or []
    question_index = state.get("current_question_index", 0)
    question_attempts = state.get("current_question_attempts", 0)
    quiz_attempts = state.get("quiz_attempts", [])
    cumulative_quiz_score = state.get("cumulative_quiz_score", 0.0)
    rehydrated = False

    session_id = state.get("session_id")
    if not quiz_questions and session_id:
        try:
            from memory.short_term import fetch_quiz_session

            sess = await fetch_quiz_session(session_id)
        except Exception:  # pragma: no cover - Redis best-effort
            sess = None
        if sess and sess.get("current_question_index", 0) < len(sess.get("quiz_questions", [])):
            quiz_session_id = sess.get("quiz_session_id", "")
            quiz_questions = sess.get("quiz_questions", [])
            question_index = sess.get("current_question_index", 0)
            question_attempts = sess.get("current_question_attempts", 0)
            quiz_attempts = sess.get("quiz_attempts", [])
            cumulative_quiz_score = sess.get("cumulative_quiz_score", 0.0)
            rehydrated = True

    quiz_in_progress = bool(
        quiz_session_id and quiz_questions and question_index < len(quiz_questions)
    )
    if quiz_in_progress and not _is_meta_command(text):
        log.info("Mid-quiz utterance detected; forcing intent=quiz")
        out: dict = {
            "intent": "quiz",
            "intent_confidence": 0.95,
            "student_answer": text,
            "next_action": "score_answer",
            "last_node": "intent_router",
        }
        if rehydrated:
            out.update(
                {
                    "quiz_session_id": quiz_session_id,
                    "quiz_questions": quiz_questions,
                    "current_question_index": question_index,
                    "current_question_attempts": question_attempts,
                    "quiz_question": quiz_questions[question_index],
                    "quiz_attempts": quiz_attempts,
                    "cumulative_quiz_score": cumulative_quiz_score,
                }
            )
        return out

    # --- LLM classification
    llm = get_router_llm()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT + language_instruction()},
            {"role": "user", "content": text},
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)

    try:
        # Strip code fences if any
        cleaned = (
            raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        decision = IntentDecision.model_validate_json(cleaned)
    except (ValidationError, json.JSONDecodeError) as exc:
        log.warning("Intent JSON parse failed: %s — falling back to tutoring", exc)
        decision = IntentDecision(
            intent="tutoring", confidence=0.4, reasoning="fallback after parse error"
        )

    log.info(
        "Intent=%s conf=%.2f emotion=%s reason=%s",
        decision.intent,
        decision.confidence,
        decision.detected_emotion,
        decision.reasoning,
    )

    out: dict = {
        "intent": decision.intent,
        "intent_confidence": decision.confidence,
        "user_input": text,
        "emotional_state": cast(str, decision.detected_emotion),
        "next_action": "route_intent",
        "last_node": "intent_router",
    }
    # Only overwrite the topic already in state when the student actually named
    # a new one — a plain follow-up ("lanjutkan") should not clobber the topic
    # an in-progress tutoring/quiz flow is already tracking.
    if decision.topic.strip():
        out["current_topic"] = decision.topic.strip()
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_META_COMMANDS = {
    "stop",
    "berhenti",
    "pause",
    "repeat",
    "ulangi",
    "ulang",
    "help",
    "tolong",
    "lebih lambat",
    "slow down",
}


def _is_meta_command(text: str) -> bool:
    """Detect quiz-control commands that should NOT be treated as answers."""
    lowered = text.lower().strip()
    return any(cmd in lowered for cmd in _META_COMMANDS) and len(lowered.split()) <= 4
