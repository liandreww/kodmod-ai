"""
KODMOD AI — Main LangGraph Orchestrator
========================================

This module assembles the four clusters into a single StateGraph:

    Cluster 1 — Practices & Tutoring   (tutoring_node, mini_quiz_node)
    Cluster 2 — Quiz / Assessment      (quiz subgraph)
    Cluster 3 — Content & Exercise     (problem_generator, rag_retrieval)
    Cluster 4 — Analytics & Reporting  (analytics_node, recommendation_node)

Flow (matches the supplied cluster diagrams)
--------------------------------------------
    speech_in → STT → intent_router ─┬─► tutoring ─► RAG ─► accessibility ─► TTS
                                     ├─► quiz_subgraph (Problem-Gen → Ask → STT
                                     │                  → Score → Analyze
                                     │                  → Update Student Model)
                                     ├─► analytics_node ─► recommendation_node
                                     └─► help / repeat / stop

Persistence
-----------
* `AsyncPostgresSaver` writes a checkpoint after every node, so:
  - Sessions survive process restarts
  - Human-in-the-loop interrupts work
  - LangSmith traces are aligned with stored state

Streaming
---------
* The graph is invoked with `astream_events` so the FastAPI WebSocket can
  forward partial TTS audio as soon as the tutoring agent emits its first
  tokens.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agents.intent_router import intent_router_node
from agents.tutoring_agent import tutoring_node
from agents.quiz_agent import quiz_node, mini_quiz_node
from agents.scoring_agent import scoring_node
from agents.quiz_analyzer import quiz_analyzer_node
from agents.problem_generator import problem_generator_node
from agents.analytics_agent import analytics_node
from agents.recommendation_agent import recommendation_node
from agents.accessibility_agent import accessibility_node
from agents.reflection_agent import reflection_node
from voice.stt import stt_node
from voice.tts import tts_node
from rag.retriever import rag_retrieval_node
from analytics.student_model import update_student_model_node

from graphs.state import KODMODState, NextAction

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
        return "end_speak"
    return "tutoring"  # safe default — explain rather than fail


def route_after_scoring(state: KODMODState) -> str:
    """
    Mirrors the Yes/No diamond after Scoring Agent in the Quiz cluster diagram.
    Yes (correct enough)  → update student model → analytics
    No (needs help)       → tutoring (remediation) → re-quiz
    """
    score = state.get("quiz_score", 0.0)
    threshold = 0.6  # configurable in settings
    if score >= threshold:
        return "update_student_model"
    return "tutoring"  # remediation loop


def route_after_analyzer(state: KODMODState) -> str:
    """After Quiz Analyzer, decide whether to keep quizzing or wrap up."""
    questions = state.get("quiz_questions", [])
    idx = state.get("current_question_index", 0)
    if idx + 1 < len(questions):
        return "quiz_ask"  # next question
    return "analytics"     # quiz finished → push to analytics cluster


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

async def build_kodmod_graph(
    checkpointer: AsyncPostgresSaver | None = None,
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
    graph.add_node("stt", stt_node)
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
    graph.add_node("tts", tts_node)

    # ---- Edges ------------------------------------------------------------
    graph.add_edge(START, "stt")
    graph.add_edge("stt", "intent_router")

    graph.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "rag_retrieval": "rag_retrieval",
            "problem_generator": "problem_generator",
            "analytics": "analytics",
            "tutoring": "tutoring",
            "end_speak": "tts",
        },
    )

    # Tutoring path
    graph.add_edge("rag_retrieval", "tutoring")
    graph.add_edge("tutoring", "reflection")     # self-check
    graph.add_edge("reflection", "accessibility")
    graph.add_edge("accessibility", "tts")

    # Mini-quiz path (inside tutoring cluster, see Practices diagram)
    graph.add_edge("mini_quiz", "scoring")

    # Quiz cluster path
    graph.add_edge("problem_generator", "quiz_ask")
    graph.add_edge("quiz_ask", "tts")            # speak the question
    # NOTE: when student answers, a NEW graph invocation re-enters at "stt"
    # and the intent router recognizes "quiz_in_progress" → routes to scoring.

    graph.add_edge("scoring", "quiz_analyzer")
    graph.add_conditional_edges(
        "quiz_analyzer",
        route_after_scoring,                     # Yes / No diamond
        {
            "update_student_model": "update_student_model",
            "tutoring": "tutoring",              # remediation loop
        },
    )
    graph.add_conditional_edges(
        "update_student_model",
        route_after_analyzer,
        {
            "quiz_ask": "quiz_ask",
            "analytics": "analytics",
        },
    )

    # Analytics cluster
    graph.add_edge("analytics", "recommendation")
    graph.add_edge("recommendation", "accessibility")

    # Final
    graph.add_edge("tts", END)

    # ---- Compile ---------------------------------------------------------
    compiled = graph.compile(
        checkpointer=checkpointer,
        # Allow pausing before tutoring for sensitive content review
        interrupt_before=[],
        # The reflection agent may decide to ask for human review
        interrupt_after=["reflection"] if checkpointer else [],
    )
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
                await ws.send_bytes(synthesize_partial(event["data"]))
    """
    async for event in graph.astream_events(state, config=config, version="v2"):
        yield event
