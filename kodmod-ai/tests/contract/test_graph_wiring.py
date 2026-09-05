"""Stage 2 — Contract: LangGraph assembly (graphs/main_graph.py).

Spec: docs/testplan/02-contract.md §3 (KM-CONTRACT-030..038).

``build_kodmod_graph`` is async and returns a compiled ``CompiledStateGraph``.
We introspect ``g.builder`` (the pre-compile ``StateGraph``) for edges/branches
because ``get_graph()`` prunes nodes it considers unreachable — which is exactly
what KM-CONTRACT-032 needs to *detect*.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.contract

NAMED_NODES = {
    "intent_router",
    "rag_retrieval",
    "tutoring",
    "mini_quiz",
    "problem_generator",
    "quiz_ask",
    "scoring",
    "quiz_analyzer",
    "update_student_model",
    "analytics",
    "recommendation",
    "accessibility",
    "reflection",
}
START = "__start__"
END = "__end__"


def _adjacency(builder) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    adj: dict[str, set[str]] = {}
    for src, dst in builder.edges:
        adj.setdefault(src, set()).add(dst)
    for src, branches in builder.branches.items():
        for br in branches.values():
            ends = getattr(br, "ends", None) or {}
            for target in ends.values():
                adj.setdefault(src, set()).add(target)
    return adj


def _reachable(adj: dict[str, set[str]], start: str = START) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


@pytest.fixture
async def compiled():  # type: ignore[no-untyped-def]
    from graphs.main_graph import build_kodmod_graph

    return await build_kodmod_graph(checkpointer=None)


# --------------------------------------------------------------------------- #
# KM-CONTRACT-030 — async compile, runnable interface
# --------------------------------------------------------------------------- #
async def test_km_contract_030_compiles_async() -> None:
    from graphs.main_graph import build_kodmod_graph

    assert inspect.iscoroutinefunction(build_kodmod_graph)
    g = await build_kodmod_graph(checkpointer=None)
    assert hasattr(g, "ainvoke")
    assert hasattr(g, "astream_events")


# --------------------------------------------------------------------------- #
# KM-CONTRACT-031 — exactly the 13 named nodes
# --------------------------------------------------------------------------- #
async def test_km_contract_031_node_set(compiled) -> None:  # type: ignore[no-untyped-def]
    nodes = set(compiled.builder.nodes) - {START, END}
    assert nodes == NAMED_NODES


# --------------------------------------------------------------------------- #
# KM-CONTRACT-032 — every node reachable from START
# --------------------------------------------------------------------------- #
async def test_km_contract_032_all_nodes_reachable_from_start(compiled) -> None:  # type: ignore[no-untyped-def]
    adj = _adjacency(compiled.builder)
    reachable = _reachable(adj)
    unreachable = sorted(NAMED_NODES - reachable)
    assert not unreachable, f"unreachable from START: {unreachable}"


# --------------------------------------------------------------------------- #
# KM-CONTRACT-033 — no node (except END) without an outbound edge/branch
# --------------------------------------------------------------------------- #
async def test_km_contract_033_no_dangling_nodes(compiled) -> None:  # type: ignore[no-untyped-def]
    adj = _adjacency(compiled.builder)
    for node in NAMED_NODES:
        assert adj.get(node), f"{node} has no outbound edge or branch"


# --------------------------------------------------------------------------- #
# KM-CONTRACT-034 — the graph never interrupts, with or without a checkpointer
# --------------------------------------------------------------------------- #
async def test_km_contract_034_no_interrupts() -> None:
    """A turn must always run to completion in one invocation.

    Reflection is an inline quality gate, not a human-in-the-loop pause, so
    neither caller has to drive a resume loop.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from graphs.main_graph import build_kodmod_graph

    none_cp = await build_kodmod_graph(checkpointer=None)
    with_cp = await build_kodmod_graph(checkpointer=InMemorySaver())
    for graph in (none_cp, with_cp):
        assert list(graph.interrupt_after_nodes) == []
        assert list(graph.interrupt_before_nodes) == []


# --------------------------------------------------------------------------- #
# KM-CONTRACT-035 — every conditional-router target is a real node
# --------------------------------------------------------------------------- #
async def test_km_contract_035_branch_targets_exist(compiled) -> None:  # type: ignore[no-untyped-def]
    valid = set(compiled.builder.nodes) | {START, END}
    for src, branches in compiled.builder.branches.items():
        for br in branches.values():
            for target in (getattr(br, "ends", None) or {}).values():
                assert target in valid, f"branch on {src} points at unknown node {target!r}"


# --------------------------------------------------------------------------- #
# KM-CONTRACT-036 — run_turn is an async generator delegating to astream_events
# --------------------------------------------------------------------------- #
def test_km_contract_036_run_turn_is_async_generator() -> None:
    from graphs.main_graph import run_turn

    assert inspect.isasyncgenfunction(run_turn)
    src = inspect.getsource(run_turn)
    assert "astream_events" in src and 'version="v2"' in src


# --------------------------------------------------------------------------- #
# KM-CONTRACT-037 — rag_retrieval_node fills next_action/last_node too  (#10)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#10 — rag_retrieval_node returns only {'retrieved_docs': ...}; the node convention "
    "requires it to also set next_action and last_node"
)
def test_km_contract_037_rag_node_sets_next_action() -> None:
    from rag.retriever import rag_retrieval_node

    src = inspect.getsource(rag_retrieval_node)
    assert "next_action" in src, "rag_retrieval_node never sets next_action"
    assert "last_node" in src, "rag_retrieval_node never sets last_node"


# --------------------------------------------------------------------------- #
# KM-CONTRACT-038 — rag_retrieval_node reads current_concept_id  (#10)
# --------------------------------------------------------------------------- #
@pytest.mark.known_bug(
    "#10 — rag_retrieval_node reads state['concept_id'] (never set anywhere); it should "
    "read state['current_concept_id']"
)
def test_km_contract_038_rag_node_reads_current_concept_id() -> None:
    from rag.retriever import rag_retrieval_node

    src = inspect.getsource(rag_retrieval_node)
    assert 'get("current_concept_id"' in src or "get('current_concept_id'" in src
    assert 'get("concept_id"' not in src and "get('concept_id'" not in src
