"""
KODMOD AI — Problem Generator Agent
====================================

Top of the **Quiz/Assessment cluster** (and also fed by the **Content & Exercise
Management cluster**, see Image 4). Produces a list of `QuizQuestion`s
calibrated to the student's mastery profile.

Inputs from state
-----------------
* `current_concept_id` — what we're quizzing on
* `current_difficulty` — coarse difficulty knob
* `mastery_scores`     — per-concept history; used to pick neighboring concepts
                         to weave in (spiral curriculum)
* `learning_profile`   — language, pace preference

The agent uses the Content cluster's RAG to ground each question in real
curriculum material so we never hallucinate facts.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast
from uuid import uuid4

from graphs.state import DifficultyLevel, KODMODState, QuizQuestion
from tools.llm_client import get_quiz_llm, language_instruction
from tools.rag_tool import RAGTool

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are KODMOD's Problem Generator. Generate a set of spoken-friendly quiz
questions for a visually impaired student.

CONSTRAINTS
- Every question must be answerable WITHOUT seeing anything.
- No diagrams, charts, images, tables. No "look at the figure" phrasing.
- Numbers under 20 spelled out in the stem. Larger numbers as digits + spoken
  form — speech engines handle digits fine.
- For MCQ: exactly 4 options, labeled A, B, C, D. Distractors must be
  plausible (don't make 3 obviously wrong).
- Mix question types across the set:
  * mcq            (1–2 per 5)
  * spoken         (short factual / one-word/number answer)
  * explain        (define / explain in own words)
  * reasoning      (why does X happen?)
  * step_by_step   (walk through a procedure)

ADAPTATION
- Difficulty given as <difficulty>. Match it.
- Mastery profile <mastery> is a JSON of concept→score. Mix in neighboring
  concepts the student knows well as scaffolding.

GROUNDING
- Use only facts present in <curriculum_context>. If context is thin, ask
  about general definitions.

OUTPUT — JSON ONLY:
{
  "questions": [
    {
      "text": "spoken question text",
      "type": "mcq|spoken|explain|reasoning|step_by_step",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],   // [] if not MCQ
      "expected_answer": "the canonical correct answer",
      "rubric": {"keywords": ["..."], "min_keywords": 2},
      "concept_id": "the primary concept tested",
      "difficulty": "beginner|easy|medium|hard|expert"
    }
    ...
  ]
}
"""


async def problem_generator_node(state: KODMODState) -> dict[str, Any]:
    requested_topic = (state.get("current_topic") or "").strip()
    concept_id = state.get("current_concept_id") or ""
    subject_id = state.get("subject_id")
    if not concept_id and requested_topic:
        concept_id = await _resolve_concept_id(requested_topic, subject_id) or ""
    if not concept_id:
        concept_id = _infer_concept(state)
    # Human-readable topic for the LLM. `concept_id` is often a UUID or "general",
    # which tells the model nothing — prefer an explicit topic label.
    topic = requested_topic or concept_id
    difficulty: DifficultyLevel = state.get("current_difficulty", "medium")
    mastery = state.get("mastery_scores", {})
    requested_n = int(state.get("quiz_n_questions") or 0)
    n_questions = requested_n if requested_n >= 1 else _decide_n_questions(state)

    # ---- Pull curriculum context from the Content cluster (RAG) ---------
    # Scope by subject_id even when concept_id can't be resolved, so retrieval
    # never falls back to an unfiltered search over the whole curriculum table.
    filters: dict[str, Any] = {}
    if concept_id:
        filters["concept_id"] = concept_id
    if subject_id:
        filters["subject_id"] = subject_id
    rag = RAGTool()
    docs = await rag.retrieve(
        query=f"{topic} learning material questions",
        k=6,
        filters=filters or None,
    )
    context_block = (
        "\n".join(f"[{i + 1}] {d.get('text', '')[:300]}" for i, d in enumerate(docs[:6]))
        or "(curriculum context unavailable — fall back to general knowledge)"
    )

    user_block = (
        f"<topic>{topic}</topic>\n"
        f"<difficulty>{difficulty}</difficulty>\n"
        f"<mastery>{json.dumps(mastery)}</mastery>\n"
        f"<concept_id>{concept_id}</concept_id>\n"
        f"<n_questions>{n_questions}</n_questions>\n"
        f"All {n_questions} questions must be about the topic above.\n"
        f"<curriculum_context>\n{context_block}\n</curriculum_context>\n\n"
        f"Generate exactly {n_questions} questions."
    )

    llm = get_quiz_llm()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT + language_instruction()},
            {"role": "user", "content": user_block},
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)

    try:
        cleaned = (
            raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.error("Problem generator JSON parse failed")
        parsed = {"questions": []}

    # Prefer the real curriculum id from state — the LLM's free-text
    # `concept_id` ("pecahan") is not a UUID and would break mastery
    # persistence downstream (`CAST(:cid AS uuid)`).
    resolved_cid = state.get("current_concept_id") or concept_id

    questions: list[QuizQuestion] = []
    for q in parsed.get("questions", []):
        questions.append(
            QuizQuestion(
                question_id=str(uuid4()),
                text=q.get("text", ""),
                type=q.get("type", "spoken"),
                options=q.get("options", []),
                expected_answer=q.get("expected_answer", ""),
                rubric=q.get("rubric", {}),
                concept_id=resolved_cid,
                difficulty=q.get("difficulty", difficulty),
            )
        )

    if not questions:
        log.warning("No questions produced; emitting one fallback")
        questions = [_fallback_question(resolved_cid, difficulty)]

    # Pad with open-ended fallbacks if the model under-delivered (it is prompted
    # for `n_questions`). When the caller asked for an explicit length, honour it
    # verbatim; otherwise a quiz is at least 3 questions.
    target_n = n_questions if requested_n >= 1 else max(n_questions, 3)
    questions = questions[:target_n]
    while len(questions) < target_n:
        questions.append(_fallback_question(resolved_cid, difficulty))

    log.info("Problem generator produced %d questions on concept=%s", len(questions), resolved_cid)

    quiz_session_id = f"quiz-{uuid4().hex[:10]}"
    session_id = state.get("session_id")
    if session_id:
        try:
            from memory.short_term import store_quiz_session

            await store_quiz_session(
                session_id,
                {
                    "quiz_session_id": quiz_session_id,
                    "quiz_questions": questions,
                    "current_question_index": 0,
                    "quiz_question": questions[0],
                    "quiz_attempts": [],
                    "cumulative_quiz_score": 0.0,
                },
            )
        except Exception:  # pragma: no cover - Redis best-effort
            log.warning("Could not persist quiz session to short-term memory", exc_info=True)

    return {
        "quiz_session_id": quiz_session_id,
        "quiz_questions": questions,
        "current_question_index": 0,
        "quiz_question": questions[0],
        "quiz_attempts": [],
        "cumulative_quiz_score": 0.0,
        "next_action": "ask_question",
        "last_node": "problem_generator",
    }


async def generate_questions_for_student(
    *,
    student_id: Any,
    concept_id: Any | None = None,
    n: int = 5,
    difficulty_hint: str | None = None,
    topic_hint: str | None = None,
) -> list[dict[str, Any]]:
    """
    Adapter used by ``POST /exercise/generate`` and ``tools/quiz_generator_tool`` —
    wraps :func:`problem_generator_node` and returns plain dicts
    (``ExerciseGenerateResponse.exercises`` is ``list[dict]``).
    """
    state: KODMODState = {
        "student_id": str(student_id),
        "current_concept_id": str(concept_id) if concept_id else "",
        "current_topic": topic_hint or "",
        "current_difficulty": cast(DifficultyLevel, difficulty_hint or "medium"),
        "mastery_scores": {},
    }
    result = await problem_generator_node(state)
    return [dict(q) for q in result.get("quiz_questions", [])][:n]


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def _decide_n_questions(state: KODMODState) -> int:
    """Use student profile + emotional state to pick quiz length."""
    emotion = state.get("emotional_state", "neutral")
    if emotion in ("fatigued", "frustrated"):
        return 3
    if emotion == "motivated":
        return 7
    return 5


async def _resolve_concept_id(topic: str, subject_id: str | None) -> str | None:
    """Match a spoken topic (e.g. "pecahan") to a real `concepts` row.

    Free text from the student is not a concept_id, so without this the RAG
    filter below silently drops (`_coerce_uuid` rejects non-UUIDs) and
    retrieval becomes unfiltered. Best-effort: any DB hiccup just falls
    through to `_infer_concept`.
    """
    import uuid

    from sqlalchemy import select

    from database.models import Concept
    from database.session import async_session

    try:
        sid: uuid.UUID | None = None
        if subject_id:
            try:
                sid = uuid.UUID(str(subject_id))
            except (ValueError, TypeError):
                sid = None
        async with async_session() as session:
            stmt = select(Concept.id).where(Concept.name.ilike(f"%{topic}%"))
            if sid is not None:
                stmt = stmt.where(Concept.subject_id == sid)
            match = (await session.execute(stmt.limit(1))).scalar_one_or_none()
            return str(match) if match else None
    except Exception:  # pragma: no cover - a lookup miss must not block a quiz
        log.warning("Concept lookup failed for topic=%r", topic, exc_info=True)
        return None


def _infer_concept(state: KODMODState) -> str:
    """If no concept_id is set, pick the weakest mastered concept."""
    scores = state.get("mastery_scores", {})
    if not scores:
        return "general"
    return min(scores.items(), key=lambda kv: kv[1])[0]


def _fallback_question(concept_id: str, difficulty: DifficultyLevel) -> QuizQuestion:
    return QuizQuestion(
        question_id=str(uuid4()),
        text=f"Coba jelaskan dengan kalimatmu sendiri: apa yang kamu pahami tentang {concept_id}?",
        type="explain",
        options=[],
        expected_answer="(open-ended)",
        rubric={"keywords": [concept_id], "min_keywords": 1},
        concept_id=concept_id,
        difficulty=difficulty,
    )
