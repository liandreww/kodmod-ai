"""
Integration test for the LangGraph assembly.

We don't run a real LLM here — the test just ensures the graph compiles,
all nodes are reachable, and the conditional routers return valid edges.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_graph_compiles():
    """The graph factory should build without import errors."""
    from graphs.main_graph import build_kodmod_graph

    graph = build_kodmod_graph(checkpointer=None)
    # Graph object should expose the runnable interface.
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream_events")


def test_state_initial_factory():
    from graphs.state import initial_state

    s = initial_state(student_id="00000000-0000-0000-0000-000000000001")
    assert s["student_id"] == "00000000-0000-0000-0000-000000000001"
    assert s["intent"] in {"unknown", None}
    assert isinstance(s["messages"], list)


def test_routers_return_known_node_names():
    from graphs.main_graph import (
        route_after_analyzer,
        route_after_intent,
        route_after_scoring,
    )
    from graphs.state import initial_state

    s = initial_state(student_id="x")

    s["intent"] = "tutoring"
    assert route_after_intent(s) == "rag_retrieval"

    s["intent"] = "quiz"
    assert route_after_intent(s) in {"problem_generator", "quiz_ask"}

    s["intent"] = "analytics"
    assert route_after_intent(s) == "analytics"

    s["quiz_score"] = 0.9
    nxt = route_after_scoring(s)
    assert nxt in {"update_student_model", "quiz_analyzer"}

    s["quiz_score"] = 0.2
    nxt = route_after_scoring(s)
    assert nxt in {"tutoring", "rag_retrieval"}
