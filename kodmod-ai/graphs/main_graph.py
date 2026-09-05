"""
KODMOD AI — Main LangGraph Orchestrator
========================================

This module assembles the four clusters into a single StateGraph:

    Cluster 1 — Practices & Tutoring   (tutoring_node, mini_quiz_node)
    Cluster 2 — Quiz / Assessment      (quiz subgraph)
    Cluster 3 — Content & Exercise     (problem_generator, rag_retrieval)
    Cluster 4 — Analytics & Reporting  (analytics_node, recommendation_node)

Flow
----
    text_in → intent_router ─┬─► RAG → tutoring → accessibility
                             ├─► quiz cluster (Problem-Gen → Ask → Score
                             │                 → Analyze → Update Student Model)
                             ├─► analytics_node → recommendation_node
                             └─► stop

The turn is text in, text out. Speech recognition and synthesis both happen in
the browser, so no node in this graph touches audio. `accessibility` is the
single terminal node for every path that produces something to say.

Persistence
-----------
* `AsyncPostgresSaver` writes a checkpoint after every node, so sessions
  survive process restarts and LangSmith traces align with stored state.

Streaming
---------
* The graph is invoked with `astream_events` so the FastAPI WebSocket can
  forward tutor tokens the moment they are produced.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agents.accessibility_agent import accessibility_node
from agents.analytics_agent import analytics_node
from agents.intent_router import intent_router_node
from agents.problem_generator import problem_generator_node
from agents.quiz_agent import mini_quiz_node, quiz_node
from agents.quiz_analyzer import quiz_analyzer_node
from agents.recommendation_agent import recommendation_node
from agents.reflection_agent import reflection_node
from agents.scoring_agent import scoring_node
from agents.tutoring_agent import tutoring_node
from analytics.student_model import update_student_model_node
from config.settings import settings
from graphs.state import KODMODState
from rag.retriever import rag_retrieval_node

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conditional routers
# ---------------------------------------------------------------------------


def route_after_intent(state: KODMODState) -> str:
    """
    First branch point — mirrors the 'What do you want?' diamond in the
    Practices & Tutoring diagram.
    """
    intent = state.get("intent", "unknown")

    # Quiz in progress: the utterance is an answer, not a new request — the
    # intent_router already forced intent="quiz". Route straight to scoring
    # instead of regenerating a fresh question set.
    questions = state.get("quiz_questions") or []
    idx = state.get("current_question_index", 0)
    quiz_in_progress = bool(state.get("quiz_session_id")) and idx < len(questions)
    if intent == "quiz" and quiz_in_progress and state.get("student_answer"):
        return "scoring"

    if intent == "tutoring":
        return "rag_retrieval"
    if intent == "quiz":
        return "problem_generator"
    if intent == "exercise_request":
        return "problem_generator"
    if intent == "analytics":
        return "analytics"
    if intent in ("repeat", "clarification"):
        return "tutoring"
    if intent == "stop":
        return "end"
    return "tutoring"  # safe default — explain rather than fail


def route_after_scoring(state: KODMODState) -> str:
    """
    Mirrors the Yes/No diamond after Scoring Agent in the Quiz cluster diagram.
    Yes (correct enough)  → update student model → analytics
    No (needs help)       → tutoring (remediation) → re-quiz

    A low score alone never blocks the quiz forever: once
    `current_question_attempts` reaches `QUIZ_MAX_ATTEMPTS_PER_QUESTION`, this
    forces the same "pass" branch regardless of score, so a question the
    student can't clear in time still lets the quiz move on.
    """
    score = state.get("quiz_score", 0.0)
    threshold = settings.QUIZ_PASS_THRESHOLD
    attempts = state.get("current_question_attempts", 0)
    if score >= threshold or attempts >= settings.QUIZ_MAX_ATTEMPTS_PER_QUESTION:
        return "update_student_model"
    return "tutoring"  # remediation loop


def route_after_tutoring(state: KODMODState) -> str:
    """
    After a tutoring explanation, optionally fire the lightweight "Mini quiz"
    comprehension check (Practices & Tutoring diagram) before self-reflection.
    Only for a plain tutoring turn on a known concept — never mid quiz session.
    """
    if (
        state.get("intent") == "tutoring"
        and state.get("current_concept_id")
        and not state.get("quiz_session_id")
    ):
        return "mini_quiz"
    return "reflection"


def route_after_student_model(state: KODMODState) -> str:
    """After the student model update, decide whether the quiz is finished.

    ``update_student_model_node`` has already advanced ``current_question_index``,
    so ``idx`` here points at the *next* unanswered question. When the quiz is
    exhausted we push to the analyzer + analytics cluster for the closing
    summary; otherwise we go straight back to ``quiz_ask`` so the next question
    is spoken within this same turn.
    """
    questions = state.get("quiz_questions", [])
    idx = state.get("current_question_index", 0)
    if idx >= len(questions):
        return "quiz_analyzer"  # quiz finished → full session analysis
    return "quiz_ask"  # more questions remain → ask the next one now


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


async def build_kodmod_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """
    Assemble and compile the KODMOD AI graph.

    Parameters
    ----------
    checkpointer : AsyncPostgresSaver
        If provided, all state transitions are persisted. In tests, pass None
        to use the in-memory `MemorySaver`.
    """
    graph = StateGraph(KODMODState)

    # --- Cluster 1: Practices & Tutoring -----------------------------------
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("rag_retrieval", rag_retrieval_node)
    graph.add_node("tutoring", tutoring_node)
    graph.add_node("mini_quiz", mini_quiz_node)

    # --- Cluster 2: Quiz / Assessment --------------------------------------
    graph.add_node("problem_generator", problem_generator_node)
    graph.add_node("quiz_ask", quiz_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("quiz_analyzer", quiz_analyzer_node)
    graph.add_node("update_student_model", update_student_model_node)

    # --- Cluster 4: Analytics & Reporting ----------------------------------
    graph.add_node("analytics", analytics_node)
    graph.add_node("recommendation", recommendation_node)

    # --- Cross-cutting -----------------------------------------------------
    graph.add_node("accessibility", accessibility_node)
    graph.add_node("reflection", reflection_node)

    # ---- Edges ------------------------------------------------------------
    graph.add_edge(START, "intent_router")

    graph.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "rag_retrieval": "rag_retrieval",
            "problem_generator": "problem_generator",
            "scoring": "scoring",
            "analytics": "analytics",
            "tutoring": "tutoring",
            "end": END,
        },
    )

    # Tutoring path
    graph.add_edge("rag_retrieval", "tutoring")
    graph.add_conditional_edges(
        "tutoring",
        route_after_tutoring,  # optional mini-quiz check, then self-reflection
        {
            "mini_quiz": "mini_quiz",
            "reflection": "reflection",
        },
    )
    graph.add_edge("reflection", "accessibility")

    # Mini-quiz path (inside tutoring cluster, see Practices diagram)
    graph.add_edge("mini_quiz", "scoring")

    # Quiz cluster path
    graph.add_edge("problem_generator", "quiz_ask")
    graph.add_edge("quiz_ask", "accessibility")  # polish the question, then deliver
    # NOTE: when the student answers, a NEW graph invocation re-enters at
    # "intent_router", which recognizes "quiz_in_progress" → routes to scoring.
    # If more questions remain, THIS SAME turn loops back to "quiz_ask" below
    # (via update_student_model → route_after_student_model) so the next
    # question is spoken immediately, rather than waiting on another utterance.

    graph.add_conditional_edges(
        "scoring",
        route_after_scoring,  # Yes / No diamond
        {
            "update_student_model": "update_student_model",
            "tutoring": "tutoring",  # remediation loop
        },
    )
    graph.add_conditional_edges(
        "update_student_model",
        route_after_student_model,
        {
            "quiz_ask": "quiz_ask",
            "quiz_analyzer": "quiz_analyzer",
        },
    )
    graph.add_edge("quiz_analyzer", "analytics")

    # Analytics cluster
    graph.add_edge("analytics", "recommendation")
    graph.add_edge("recommendation", "accessibility")

    # Final — every speaking path converges here.
    graph.add_edge("accessibility", END)

    # ---- Compile ---------------------------------------------------------
    # No interrupts: reflection runs as an inline quality gate rather than a
    # human-in-the-loop pause, so a turn always completes in one invocation.
    compiled = graph.compile(checkpointer=checkpointer)
    log.info("KODMOD graph compiled with %d nodes", len(graph.nodes))
    return compiled


# ---------------------------------------------------------------------------
# Convenience runner used by FastAPI
# ---------------------------------------------------------------------------


async def run_turn(
    graph,
    state: KODMODState,
    config: dict[str, Any],
):
    """
    Stream events for a single conversational turn.

    Usage in FastAPI WebSocket handler::

        async for event in run_turn(graph, state, {"configurable": {"thread_id": sid}}):
            if event["event"] == "on_chat_model_stream":
                await ws.send_json({"type": "token", "text": ...})
    """
    async for event in graph.astream_events(state, config=config, version="v2"):
        yield event
