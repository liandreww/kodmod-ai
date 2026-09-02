"""Stage 3 §10-11 — whole-graph invocation per intent (stub LLM, real DB).

Spec: docs/testplan/03-integration.md §10 (KM-INT-140..146) and §11 (KM-INT-150..154).
The §11 quiz multi-turn group is the quiz-feature definition-of-done and is
currently unreachable from START (#11 / BUG-3) — those carry @known_bug.
"""

from __future__ import annotations

import json
import sys
import uuid

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text

# AsyncPostgresSaver -> psycopg async cannot run on Windows' ProactorEventLoop.
# The checkpointer persistence contract is proven on Linux CI here and, black-box,
# by Stage 7 KM-SYS-010/011 (restart survival) against the real api container.
_needs_pg_saver = pytest.mark.skipif(
    sys.platform == "win32",
    reason="psycopg async needs SelectorEventLoop (Linux CI / Stage 7 cover this)",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.redis,
    pytest.mark.asyncio(loop_scope="session"),
]


class _RouterLLM:
    """Forces the intent_router to classify as ``intent``."""

    def __init__(self, intent: str) -> None:
        self._intent = intent

    async def ainvoke(self, *_a, **_k):
        return AIMessage(content=json.dumps({"intent": self._intent, "confidence": 0.95}))

    def with_structured_output(self, *_a, **_k):
        return self


@pytest.fixture
def force_intent(monkeypatch):  # type: ignore[no-untyped-def]
    def _force(intent: str) -> None:
        import agents.intent_router as ir

        monkeypatch.setattr(ir, "get_router_llm", lambda *a, **k: _RouterLLM(intent))

    return _force


def _cfg(sid: str) -> dict:
    return {"configurable": {"thread_id": sid}}


async def _run(graph, intent_state, sid):  # type: ignore[no-untyped-def]
    return await graph.ainvoke(intent_state, config=_cfg(sid))


# --------------------------------------------------------------------------- #
# KM-INT-140 — tutoring path
# --------------------------------------------------------------------------- #
async def test_km_int_140_tutoring_path(graph, force_intent, clean_db, make_student) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("tutoring")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "tolong jelaskan apa itu pecahan"

    final = await _run(graph, state, sid)
    assert final["last_node"] == "tts"
    assert final.get("accessible_response", "").strip()
    assert final.get("audio_response_path", "") == ""  # TTS disabled


# --------------------------------------------------------------------------- #
# KM-INT-141 — analytics path
# --------------------------------------------------------------------------- #
async def test_km_int_141_analytics_path(
    graph, force_intent, clean_db, make_student, concept_ids, seed_mastery
) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("analytics")
    st = await make_student()
    await seed_mastery(st.id, {concept_ids["pecahan"]: 0.6, concept_ids["fotosintesis"]: 0.3})
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "bagaimana perkembangan belajarku"

    final = await _run(graph, state, sid)
    assert final["last_node"] == "tts"
    assert "overall_mastery" in final.get("analytics_summary", {})


# --------------------------------------------------------------------------- #
# KM-INT-142 — stop path (fast: intent_router -> end_speak -> tts -> END)
# --------------------------------------------------------------------------- #
async def test_km_int_142_stop_path(graph, force_intent, clean_db, make_student) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("stop")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "berhenti"

    final = await _run(graph, state, sid)
    assert final["last_node"] == "tts"
    # never entered a cluster node
    assert not final.get("retrieved_docs")
    assert not final.get("quiz_questions")


# --------------------------------------------------------------------------- #
# KM-INT-143 — quiz-start path
# --------------------------------------------------------------------------- #
async def test_km_int_143_quiz_start_path(
    graph, force_intent, clean_db, make_student, concept_ids
) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("quiz")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "beri aku kuis pecahan"
    state["current_concept_id"] = str(concept_ids["pecahan"])

    final = await _run(graph, state, sid)
    assert final["last_node"] == "tts"
    assert final.get("quiz_questions")
    assert final.get("quiz_session_id", "").startswith("quiz-")


# --------------------------------------------------------------------------- #
# KM-INT-144 / 145 — checkpointer persistence + resume across interrupt
# --------------------------------------------------------------------------- #
@_needs_pg_saver
async def test_km_int_144_checkpointer_writes(
    checkpointed_graph, force_intent, clean_db, make_student
) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session
    from graphs.state import initial_state

    force_intent("tutoring")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "jelaskan pecahan"

    await checkpointed_graph.ainvoke(state, config=_cfg(sid))
    async with async_session() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :tid"), {"tid": sid}
            )
        ).scalar_one()
    assert n >= 1


@_needs_pg_saver
async def test_km_int_145_resume_from_interrupt(
    checkpointed_graph, force_intent, clean_db, make_student
) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("tutoring")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "jelaskan pecahan"

    # interrupt_after=["reflection"] when a checkpointer is present
    mid = await checkpointed_graph.ainvoke(state, config=_cfg(sid))
    assert mid.get("last_node") == "reflection"

    final = await checkpointed_graph.ainvoke(None, config=_cfg(sid))
    assert final["last_node"] == "tts"
    assert final.get("accessible_response", "").strip()


# --------------------------------------------------------------------------- #
# KM-INT-146 — initial_state carries every field every node needs
# --------------------------------------------------------------------------- #
async def test_km_int_146_initial_state_is_sufficient(
    graph, force_intent, clean_db, make_student
) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("tutoring")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "jelaskan pecahan senilai"
    final = await _run(graph, state, sid)  # must not raise KeyError anywhere
    assert final["session_id"] == sid
    assert final["student_id"] == str(st.id)


# --------------------------------------------------------------------------- #
# §11 — quiz multi-turn (target path, currently unreachable)  #11 / BUG-3
# --------------------------------------------------------------------------- #
@pytest.fixture
async def quiz_started(graph, force_intent, clean_db, make_student, concept_ids):  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    force_intent("quiz")
    st = await make_student()
    sid = str(uuid.uuid4())
    state = initial_state(session_id=sid, student_id=str(st.id))
    state["user_input"] = "kuis pecahan"
    state["current_concept_id"] = str(concept_ids["pecahan"])
    final = await graph.ainvoke(state, config=_cfg(sid))
    return graph, sid, str(st.id), final


@pytest.mark.known_bug(
    "#11 / BUG-3 — quiz start should produce >= 3 questions and set quiz_question"
)
async def test_km_int_150_quiz_start_produces_questions(quiz_started) -> None:  # type: ignore[no-untyped-def]
    _g, _sid, _stid, final = quiz_started
    assert len(final.get("quiz_questions", [])) >= 3
    assert final.get("quiz_question")


@pytest.mark.known_bug(
    "#11 / BUG-3 — the next utterance (an answer) re-enters at stt, and route_after_intent "
    "has no 'quiz in progress' branch to reach scoring; quiz_attempts never grows"
)
async def test_km_int_151_answer_reaches_scoring(quiz_started) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    g, sid, stid, _final = quiz_started
    turn2 = initial_state(session_id=sid, student_id=stid)
    turn2["user_input"] = "A"
    out = await g.ainvoke(turn2, config=_cfg(sid))
    assert out.get("quiz_attempts"), "answer never scored"
    assert out.get("quiz_score") is not None


@pytest.mark.known_bug(
    "#11 / #12 — scoring -> quiz_analyzer, route_after_scoring on QUIZ_PASS_THRESHOLD"
)
async def test_km_int_152_score_routes_on_threshold(quiz_started) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    g, sid, stid, _final = quiz_started
    turn2 = initial_state(session_id=sid, student_id=stid)
    turn2["user_input"] = "A"
    out = await g.ainvoke(turn2, config=_cfg(sid))
    assert out.get("last_node") in {"quiz_analyzer", "update_student_model", "tutoring"}


@pytest.mark.known_bug("#11 — route_after_analyzer advances to the next question while idx+1 < len")
async def test_km_int_153_next_question(quiz_started) -> None:  # type: ignore[no-untyped-def]
    from graphs.state import initial_state

    g, sid, stid, _final = quiz_started
    turn2 = initial_state(session_id=sid, student_id=stid)
    turn2["user_input"] = "A"
    out = await g.ainvoke(turn2, config=_cfg(sid))
    assert out.get("current_question_index", 0) >= 1


@pytest.mark.known_bug("#11 — finishing every question runs analytics and persists mastery")
async def test_km_int_154_quiz_exhausted_runs_analytics(quiz_started) -> None:  # type: ignore[no-untyped-def]
    from database.session import async_session
    from graphs.state import initial_state

    g, sid, stid, final = quiz_started
    n = max(1, len(final.get("quiz_questions", [])))
    for _ in range(n):
        t = initial_state(session_id=sid, student_id=stid)
        t["user_input"] = "A"
        await g.ainvoke(t, config=_cfg(sid))
    async with async_session() as s:
        rows = (
            await s.execute(
                text("SELECT count(*) FROM mastery_scores WHERE student_id = CAST(:sid AS uuid)"),
                {"sid": stid},
            )
        ).scalar_one()
    assert rows >= 1
