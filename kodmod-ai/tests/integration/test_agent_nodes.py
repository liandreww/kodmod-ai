"""Stage 3 §9 — agent node functions in isolation (real DB + Redis, stub LLM/embeddings).

Spec: docs/testplan/03-integration.md §9 (KM-INT-100..124).
Each node is called ``await <node>(state)`` with a hand-assembled state; we assert
the key return fields plus ``last_node`` / ``next_action``.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.redis,
    pytest.mark.asyncio(loop_scope="session"),
]


class _GarbageLLM:
    """Stub chat model that always returns non-JSON prose (forces parse-fail paths)."""

    async def ainvoke(self, *_a, **_k):
        from langchain_core.messages import AIMessage

        return AIMessage(content="maaf ini bukan json sama sekali")

    def with_structured_output(self, *_a, **_k):
        return self


def _patch_getter(monkeypatch, module: str, name: str, value) -> None:
    import importlib

    mod = importlib.import_module(module)
    monkeypatch.setattr(mod, name, lambda *a, **k: value)


# --------------------------------------------------------------------------- #
# intent_router
# --------------------------------------------------------------------------- #
async def test_km_int_100_intent_router_happy_and_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from agents.intent_router import intent_router_node

    out = await intent_router_node({"transcribed_text": "tolong jelaskan pecahan"})
    assert out["intent"] == "tutoring"
    assert out["last_node"] == "intent_router"

    _patch_getter(monkeypatch, "agents.intent_router", "get_router_llm", _GarbageLLM())
    out2 = await intent_router_node({"transcribed_text": "hmm apa ya"})
    assert out2["intent"] == "tutoring"  # safe fallback on parse failure


async def test_km_int_101_intent_router_midquiz_forces_quiz() -> None:
    from agents.intent_router import intent_router_node

    state = {
        "transcribed_text": "jawabannya adalah dua per empat",
        "quiz_session_id": "quiz-abc",
        "quiz_questions": [{"question_id": "q1"}, {"question_id": "q2"}],
        "current_question_index": 0,
    }
    out = await intent_router_node(state)
    assert out["intent"] == "quiz"
    assert out["student_answer"] == "jawabannya adalah dua per empat"
    assert out["next_action"] == "score_answer"


async def test_km_int_102_intent_router_meta_command_not_forced() -> None:
    from agents.intent_router import intent_router_node

    state = {
        "transcribed_text": "ulangi",
        "quiz_session_id": "quiz-abc",
        "quiz_questions": [{"question_id": "q1"}],
        "current_question_index": 0,
    }
    out = await intent_router_node(state)
    assert out["intent"] != "quiz"  # meta-command escapes the mid-quiz short-circuit


# --------------------------------------------------------------------------- #
# tutoring
# --------------------------------------------------------------------------- #
async def test_km_int_103_tutoring_node() -> None:
    from agents.tutoring_agent import tutoring_node

    state = {
        "user_input": "apa itu pecahan",
        "current_concept_id": "pecahan",
        "mastery_scores": {"pecahan": 0.4},
        "retrieved_docs": [{"text": "Pecahan adalah bagian dari keseluruhan.", "source": "m.md"}],
    }
    out = await tutoring_node(state)
    assert out["generated_response"].strip()
    assert out["next_action"] == "accessibility_polish"
    assert out["last_node"] == "tutoring"
    assert len(out["messages"]) == 2  # HumanMessage + AIMessage


# --------------------------------------------------------------------------- #
# problem_generator / quiz_ask / mini_quiz
# --------------------------------------------------------------------------- #
async def test_km_int_104_problem_generator_node(clean_db) -> None:  # type: ignore[no-untyped-def]
    from agents.problem_generator import problem_generator_node

    out = await problem_generator_node(
        {"current_concept_id": "pecahan", "current_topic": "pecahan", "emotional_state": "neutral"}
    )
    assert out["quiz_session_id"].startswith("quiz-")
    assert len(out["quiz_questions"]) >= 1
    assert out["current_question_index"] == 0
    assert out["quiz_attempts"] == []
    assert out["next_action"] == "ask_question"


async def test_km_int_105_quiz_node_asks_current_question() -> None:
    from agents.quiz_agent import quiz_node

    q = {
        "question_id": "q1",
        "text": "Berapa satu per dua tambah satu per dua?",
        "type": "mcq",
        "options": ["A. satu", "B. dua"],
        "concept_id": "pecahan",
    }
    out = await quiz_node({"quiz_questions": [q], "current_question_index": 0})
    assert out["quiz_question"] == q
    assert out["generated_response"].strip()
    assert out["next_action"] == "speak"


async def test_km_int_106_mini_quiz_node() -> None:
    from agents.quiz_agent import mini_quiz_node

    out = await mini_quiz_node(
        {
            "generated_response": "Pecahan adalah bagian dari keseluruhan.",
            "current_concept_id": "pecahan",
        }
    )
    assert out["last_node"] == "mini_quiz"
    assert out["next_action"] == "speak"
    # fake payload is a valid JSON object -> a single question is emitted
    assert len(out.get("quiz_questions", [])) == 1
    assert out["quiz_session_id"].startswith("mini-")


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
async def test_km_int_107_scoring_mcq() -> None:
    from agents.scoring_agent import scoring_node

    state = {
        "quiz_question": {
            "question_id": "q1",
            "type": "mcq",
            "expected_answer": "A",
            "options": ["A. satu", "B. dua"],
            "concept_id": "pecahan",
        },
        "student_answer": "A",
        "quiz_attempts": [],
    }
    out = await scoring_node(state)
    assert len(out["quiz_attempts"]) == 1
    assert out["quiz_score"] == pytest.approx(1.0)
    assert out["cumulative_quiz_score"] == pytest.approx(1.0)
    assert out["next_action"] == "analyze_quiz"


async def test_km_int_108_scoring_spoken_semantic() -> None:
    from agents.scoring_agent import scoring_node

    phrase = "pecahan adalah bagian dari keseluruhan"
    out = await scoring_node(
        {
            "quiz_question": {
                "question_id": "q1",
                "type": "spoken",
                "expected_answer": phrase,
                "concept_id": "pecahan",
            },
            "student_answer": phrase,
            "quiz_attempts": [],
        }
    )
    # identical text -> stub-embedding cosine ~1 -> clip((1-0.3)/0.6)=1
    assert out["quiz_score"] == pytest.approx(1.0, abs=1e-6)


async def test_km_int_109_scoring_rubric_llm() -> None:
    from agents.scoring_agent import scoring_node

    out = await scoring_node(
        {
            "quiz_question": {
                "question_id": "q1",
                "type": "explain",
                "expected_answer": "penjelasan",
                "rubric": {"keywords": ["pembilang", "penyebut"]},
                "concept_id": "pecahan",
            },
            "student_answer": "pecahan punya pembilang dan penyebut",
            "quiz_attempts": [],
        }
    )
    assert out["quiz_score"] == pytest.approx(0.85)
    assert out["next_action"] == "analyze_quiz"


# --------------------------------------------------------------------------- #
# quiz_analyzer
# --------------------------------------------------------------------------- #
async def test_km_int_110_quiz_analyzer_node() -> None:
    from agents.quiz_analyzer import quiz_analyzer_node

    state = {
        "quiz_questions": [
            {"question_id": "q1", "concept_id": "pecahan", "text": "a"},
            {"question_id": "q2", "concept_id": "pecahan", "text": "b"},
        ],
        "quiz_attempts": [
            {"question_id": "q1", "score": 1.0, "is_correct": True, "student_answer": "A"},
            {"question_id": "q2", "score": 0.0, "is_correct": False, "student_answer": "B"},
        ],
    }
    out = await quiz_analyzer_node(state)
    assert out["next_action"] == "update_student_model"
    summary = out["analytics_summary"]
    assert summary["concept_averages"]["pecahan"] == pytest.approx(0.5)
    assert "teacher_summary" in summary


async def test_km_int_111_quiz_analyzer_json_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from agents.quiz_analyzer import quiz_analyzer_node

    _patch_getter(monkeypatch, "agents.quiz_analyzer", "get_scoring_llm", _GarbageLLM())
    state = {
        "quiz_questions": [{"question_id": "q1", "concept_id": "pecahan", "text": "a"}],
        "quiz_attempts": [{"question_id": "q1", "score": 0.2, "is_correct": False}],
    }
    out = await quiz_analyzer_node(state)
    assert out["next_action"] == "update_student_model"
    assert "pecahan" in out["analytics_summary"]["weak_concepts"]  # deterministic fallback


# --------------------------------------------------------------------------- #
# analytics
# --------------------------------------------------------------------------- #
async def test_km_int_113_analytics_node(make_student, concept_ids, seed_mastery) -> None:  # type: ignore[no-untyped-def]
    from agents.analytics_agent import analytics_node

    st = await make_student()
    await seed_mastery(st.id, {concept_ids["pecahan"]: 0.6, concept_ids["fotosintesis"]: 0.3})
    out = await analytics_node({"student_id": str(st.id)})
    assert out["next_action"] == "recommend"
    assert out["last_node"] == "analytics"
    assert "overall_mastery" in out["analytics_summary"]
    assert out["generated_response"].strip()


async def test_km_int_114_analytics_node_bad_student_id() -> None:
    from agents.analytics_agent import analytics_node

    out = await analytics_node({"student_id": "not-a-uuid"})
    assert out["next_action"] == "recommend"
    assert out["last_node"] == "analytics"


# --------------------------------------------------------------------------- #
# recommendation
# --------------------------------------------------------------------------- #
async def test_km_int_115_recommendation_node() -> None:
    from agents.recommendation_agent import recommendation_node

    out = await recommendation_node(
        {
            "analytics_summary": {"weak_concepts": ["pecahan"]},
            "learning_profile": {"language": "id"},
        }
    )
    assert isinstance(out["recommendations"], list)
    assert all(isinstance(r, str) for r in out["recommendations"])
    assert "structured_recommendations" in out["analytics_summary"]
    assert out["next_action"] == "accessibility_polish"


async def test_km_int_116_recommendation_node_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from agents.recommendation_agent import recommendation_node

    _patch_getter(
        monkeypatch, "agents.recommendation_agent", "get_recommendation_llm", _GarbageLLM()
    )
    out = await recommendation_node({"analytics_summary": {"weak_concepts": ["pecahan"]}})
    assert out["recommendations"]  # _fallback(summary) kicked in, no crash


# --------------------------------------------------------------------------- #
# accessibility
# --------------------------------------------------------------------------- #
async def test_km_int_117_accessibility_node_polish() -> None:
    from agents.accessibility_agent import accessibility_node
    from tests._fakes.accessibility_asserts import assert_no_markdown, assert_no_visual_refs

    text = "**Penting**: lihat gambar di atas. Nilai 3.2 sangat baik."
    out = await accessibility_node({"generated_response": text})
    acc = out["accessible_response"]
    assert_no_markdown(acc)
    assert_no_visual_refs(acc)
    assert "3 titik 2" in acc
    assert out["next_action"] == "speak"


async def test_km_int_118_accessibility_node_simplify_flag() -> None:
    from agents.accessibility_agent import accessibility_node

    out = await accessibility_node(
        {
            "generated_response": "Fotosintesis adalah proses biokimia kompleks pada tumbuhan.",
            "accessibility_flags": {"simplify_language": True},
        }
    )
    assert out["accessible_response"].strip()  # simplifier stub ran, no crash
    assert out["next_action"] == "speak"


async def test_km_int_119_accessibility_node_empty() -> None:
    from agents.accessibility_agent import accessibility_node

    out = await accessibility_node({"generated_response": ""})
    assert out["accessible_response"] == ""
    assert out["last_node"] == "accessibility"


# --------------------------------------------------------------------------- #
# reflection
# --------------------------------------------------------------------------- #
async def test_km_int_120_reflection_node_good_score() -> None:
    from agents.reflection_agent import reflection_node

    out = await reflection_node(
        {"generated_response": "Penjelasan yang cukup jelas.", "user_input": "x"}
    )
    assert out["next_action"] == "accessibility_polish"
    assert out["analytics_summary"]["last_reflection_score"] == pytest.approx(0.8)


async def test_km_int_121_reflection_node_low_score_interrupts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json

    from langchain_core.messages import AIMessage

    from agents.reflection_agent import reflection_node

    class _LowLLM:
        async def ainvoke(self, *_a, **_k):
            return AIMessage(
                content=json.dumps(
                    {
                        "overall_score": 0.3,
                        "needs_rewrite": True,
                        "rewritten": "Versi lebih baik.",
                        "issues": ["kurang scaffolding"],
                    }
                )
            )

    _patch_getter(monkeypatch, "agents.reflection_agent", "get_router_llm", _LowLLM())
    out = await reflection_node({"generated_response": "buruk", "user_input": "x"})
    assert out.get("interrupt_reason")
    assert out["generated_response"] == "Versi lebih baik."


async def test_km_int_122_reflection_node_parse_fail(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from agents.reflection_agent import reflection_node

    _patch_getter(monkeypatch, "agents.reflection_agent", "get_router_llm", _GarbageLLM())
    out = await reflection_node({"generated_response": "teks apa saja", "user_input": "x"})
    assert out["next_action"] == "accessibility_polish"
    assert "generated_response" not in out  # pass-through, unchanged


# --------------------------------------------------------------------------- #
# accessibility is the terminal node for every speaking path
# --------------------------------------------------------------------------- #
async def test_km_int_123_accessibility_is_the_last_node() -> None:
    """There is no speech node behind this one; whatever it emits is delivered."""
    from agents.accessibility_agent import accessibility_node

    out = await accessibility_node({"generated_response": "**Halo**, apa kabar?"})
    assert out["last_node"] == "accessibility"
    assert out["next_action"] == "respond"
    assert "**" not in out["accessible_response"]


async def test_km_int_124_accessibility_handles_empty_input() -> None:
    from agents.accessibility_agent import accessibility_node

    out = await accessibility_node({"generated_response": ""})
    assert out["accessible_response"] == ""
    assert out["next_action"] == "respond"
