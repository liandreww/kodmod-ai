"""
KODMOD AI — Central LangGraph State Schema
===========================================

This is the single source of truth for state passed between all agents in the
LangGraph orchestrator. Every node reads and writes a subset of these fields.

Design notes
------------
* `messages` uses LangGraph's `add_messages` reducer so chat history accumulates
  rather than being overwritten.
* `mastery_scores` is a sparse dict keyed by concept_id; updates merge.
* `audio_response_path` and `audio_input_path` are S3/MinIO URIs, not bytes,
  to keep the state checkpoint small.
* Every field has an explicit default so partial state updates never crash a
  downstream node.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

Intent = Literal[
    "tutoring",
    "quiz",
    "analytics",
    "clarification",
    "exercise_request",
    "help",
    "navigation",
    "repeat",
    "stop",
    "unknown",
]

DifficultyLevel = Literal["beginner", "easy", "medium", "hard", "expert"]

EmotionalState = Literal[
    "neutral", "engaged", "confused", "frustrated", "fatigued", "motivated"
]

NextAction = Literal[
    "route_intent",
    "tutor",
    "generate_quiz",
    "ask_question",
    "score_answer",
    "analyze_quiz",
    "update_student_model",
    "generate_analytics",
    "recommend",
    "accessibility_polish",
    "speak",
    "end",
    "interrupt_human",
]


# ---------------------------------------------------------------------------
# Sub-structures (kept as TypedDicts so the entire state remains JSON-safe
# for checkpoint serialization).
# ---------------------------------------------------------------------------

class TutoringTurn(TypedDict, total=False):
    role: Literal["student", "tutor"]
    text: str
    timestamp: str
    concept_id: str | None
    confusion_detected: bool


class QuizQuestion(TypedDict, total=False):
    question_id: str
    text: str
    type: Literal["mcq", "spoken", "explain", "reasoning", "step_by_step"]
    options: list[str]            # for MCQ; empty for spoken
    expected_answer: str
    rubric: dict[str, Any]
    concept_id: str
    difficulty: DifficultyLevel


class QuizAttempt(TypedDict, total=False):
    question_id: str
    student_answer: str
    score: float                  # 0.0 – 1.0
    is_correct: bool
    confidence: float
    response_latency_ms: int
    feedback: str


class RetrievedDoc(TypedDict, total=False):
    doc_id: str
    chunk_id: str
    text: str
    score: float
    source: str
    concept_ids: list[str]


class LearningProfile(TypedDict, total=False):
    learning_style: Literal["auditory", "kinesthetic", "mixed"]
    preferred_pace: Literal["slow", "normal", "fast"]
    preferred_voice: str
    language: str
    accessibility: dict[str, Any]   # screen_reader, contrast, font_scale, etc.


class AnalyticsSummary(TypedDict, total=False):
    overall_mastery: float
    weak_concepts: list[str]
    strong_concepts: list[str]
    streak_days: int
    sessions_total: int
    avg_quiz_score: float
    engagement_index: float
    recommendations: list[str]


# ---------------------------------------------------------------------------
# Master State
# ---------------------------------------------------------------------------

class KODMODState(TypedDict, total=False):
    """Central state for the KODMOD LangGraph orchestrator."""

    # ---- Identity & session -------------------------------------------------
    session_id: str
    student_id: str
    teacher_id: str | None
    request_id: str

    # ---- Voice I/O ---------------------------------------------------------
    audio_input_path: str          # URI of inbound audio chunk
    transcribed_text: str          # output of STT
    user_input: str                # canonicalized text (post-cleaning)
    audio_response_path: str       # URI of TTS output
    detected_language: str

    # ---- Routing & intent --------------------------------------------------
    intent: Intent
    intent_confidence: float
    next_action: NextAction
    interrupt_reason: str | None   # for human-in-the-loop pauses

    # ---- Tutoring context --------------------------------------------------
    current_topic: str
    current_concept_id: str
    current_difficulty: DifficultyLevel
    tutoring_context: list[TutoringTurn]
    retrieved_docs: list[RetrievedDoc]
    generated_response: str        # raw LLM output before accessibility pass
    accessible_response: str       # post-accessibility-agent text for TTS

    # ---- Quiz state --------------------------------------------------------
    quiz_session_id: str
    quiz_questions: list[QuizQuestion]
    current_question_index: int
    quiz_question: QuizQuestion    # the question currently being asked
    student_answer: str
    quiz_attempts: list[QuizAttempt]
    quiz_score: float              # 0.0 – 1.0 for current attempt
    cumulative_quiz_score: float   # session-wide
    misconceptions_detected: list[str]

    # ---- Student model & analytics ----------------------------------------
    mastery_scores: dict[str, float]      # concept_id -> 0.0..1.0
    learning_profile: LearningProfile
    analytics_summary: AnalyticsSummary
    recommendations: list[str]

    # ---- Affect / accessibility -------------------------------------------
    emotional_state: EmotionalState
    accessibility_flags: dict[str, bool]  # e.g. {"slow_speech": True}

    # ---- Conversation history (LangGraph reducer) -------------------------
    messages: Annotated[list[BaseMessage], add_messages]

    # ---- Telemetry --------------------------------------------------------
    trace_id: str
    started_at: str
    last_node: str
    error: str | None


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def initial_state(
    session_id: str,
    student_id: str,
    audio_input_path: str | None = None,
    teacher_id: str | None = None,
) -> KODMODState:
    """Return a clean state object for a new turn."""
    from datetime import datetime, timezone
    from uuid import uuid4

    return KODMODState(
        session_id=session_id,
        student_id=student_id,
        teacher_id=teacher_id,
        request_id=str(uuid4()),
        audio_input_path=audio_input_path or "",
        transcribed_text="",
        user_input="",
        audio_response_path="",
        detected_language="id",
        intent="unknown",
        intent_confidence=0.0,
        next_action="route_intent",
        interrupt_reason=None,
        current_topic="",
        current_concept_id="",
        current_difficulty="medium",
        tutoring_context=[],
        retrieved_docs=[],
        generated_response="",
        accessible_response="",
        quiz_session_id="",
        quiz_questions=[],
        current_question_index=0,
        quiz_question={},
        student_answer="",
        quiz_attempts=[],
        quiz_score=0.0,
        cumulative_quiz_score=0.0,
        misconceptions_detected=[],
        mastery_scores={},
        learning_profile={},
        analytics_summary={},
        recommendations=[],
        emotional_state="neutral",
        accessibility_flags={},
        messages=[],
        trace_id=str(uuid4()),
        started_at=datetime.now(timezone.utc).isoformat(),
        last_node="entry",
        error=None,
    )
