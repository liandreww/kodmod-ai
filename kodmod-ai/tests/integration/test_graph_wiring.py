"""Integration smoke for the LangGraph assembly.

Historically this file called ``build_kodmod_graph`` without ``await`` and built
``initial_state`` without ``session_id`` (bug #18 / L-14). It is kept as a thin
smoke; the full wiring contract lives in ``tests/contract/test_graph_wiring.py``
(KM-CONTRACT-030..038) and per-intent execution in ``test_graph_paths.py``.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def test_graph_compiles() -> None:
    from graphs.main_graph import build_kodmod_graph

    graph = await build_kodmod_graph(checkpointer=None)
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream_events")


def test_state_initial_factory() -> None:
    from graphs.state import initial_state

    s = initial_state(session_id="s-1", student_id="00000000-0000-0000-0000-000000000001")
    assert s["session_id"] == "s-1"
    assert s["student_id"] == "00000000-0000-0000-0000-000000000001"
    assert s["intent"] == "unknown"
    assert isinstance(s["messages"], list)


def test_routers_return_known_node_names() -> None:
    from graphs.main_graph import route_after_intent, route_after_scoring
    from graphs.state import initial_state

    s = initial_state(session_id="s", student_id="x")

    s["intent"] = "tutoring"
    assert route_after_intent(s) == "rag_retrieval"
    s["intent"] = "quiz"
    assert route_after_intent(s) in {"problem_generator", "quiz_ask"}
    s["intent"] = "analytics"
    assert route_after_intent(s) == "analytics"
    s["intent"] = "stop"
    assert route_after_intent(s) == "end_speak"

    s["quiz_score"] = 0.9
    assert route_after_scoring(s) in {"update_student_model", "quiz_analyzer"}
    s["quiz_score"] = 0.2
    assert route_after_scoring(s) in {"tutoring", "rag_retrieval"}
