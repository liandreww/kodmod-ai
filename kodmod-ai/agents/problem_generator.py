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
from typing import Any
from uuid import uuid4

from graphs.state import DifficultyLevel, KODMODState, QuizQuestion
from tools.llm_client import get_quiz_llm
from tools.rag_tool import RAGTool

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are KODMOD's Problem Generator. Generate a set of spoken-friendly quiz
questions for a visually impaired student.

CONSTRAINTS
- Every question must be answerable WITHOUT seeing anything.
- No diagrams, charts, images, tables. No "look at the figure" phrasing.
- Numbers under 20 spelled out in the stem. Larger numbers as digits + spoken
  form — the TTS handles digits fine.
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
    concept_id = state.get("current_concept_id") or _infer_concept(state)
    difficulty: DifficultyLevel = state.get("current_difficulty", "medium")
    mastery = state.get("mastery_scores", {})
    n_questions = _decide_n_questions(state)

    # ---- Pull curriculum context from the Content cluster (RAG) ---------
    rag = RAGTool()
    docs = await rag.retrieve(
        query=f"{concept_id} learning material questions",
        k=6,
        filters={"concept_id": concept_id} if concept_id else None,
    )
    context_block = "\n".join(
        f"[{i+1}] {d.get('text','')[:300]}" for i, d in enumerate(docs[:6])
    ) or "(curriculum context unavailable — fall back to general knowledge)"

    user_block = (
        f"<difficulty>{difficulty}</difficulty>\n"
        f"<mastery>{json.dumps(mastery)}</mastery>\n"
        f"<concept_id>{concept_id}</concept_id>\n"
        f"<n_questions>{n_questions}</n_questions>\n"
        f"<curriculum_context>\n{context_block}\n</curriculum_context>\n\n"
        f"Generate exactly {n_questions} questions."
    )

    llm = get_quiz_llm()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)

    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.error("Problem generator JSON parse failed")
        parsed = {"questions": []}

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
                concept_id=q.get("concept_id", concept_id),
                difficulty=q.get("difficulty", difficulty),
            )
        )

    if not questions:
        log.warning("No questions produced; emitting one fallback")
        questions = [_fallback_question(concept_id, difficulty)]

    log.info("Problem generator produced %d questions on concept=%s",
             len(questions), concept_id)

    return {
        "quiz_session_id": f"quiz-{uuid4().hex[:10]}",
        "quiz_questions": questions,
        "current_question_index": 0,
        "quiz_attempts": [],
        "cumulative_quiz_score": 0.0,
        "next_action": "ask_question",
        "last_node": "problem_generator",
    }


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
