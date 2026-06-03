"""
KODMOD AI — Scoring Agent
=========================

Evaluates a student's answer to a quiz question. Combines three signals:

1. **Exact match** — for MCQ and short factual answers.
2. **Semantic similarity** — embedding cosine vs. expected answer (handles
   paraphrasing in spoken responses where the student may say the right thing
   in their own words).
3. **LLM rubric grading** — for explanation / reasoning / step-by-step
   questions, an LLM applies the rubric stored on the question.

Outputs a `QuizAttempt` appended to `state["quiz_attempts"]` and updates
`state["quiz_score"]` with the score for THIS attempt (0.0–1.0).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from graphs.state import KODMODState, QuizAttempt
from rag.embeddings import embed_text
from tools.llm_client import get_scoring_llm

log = logging.getLogger(__name__)


RUBRIC_PROMPT = """\
You are a strict but fair grader for spoken student answers.

Given:
- The question
- The expected answer
- The rubric (criteria + keywords)
- The student's answer (transcribed from speech, may have minor STT errors)

Score 0.0–1.0 considering:
- Correctness of the core idea
- Coverage of rubric keywords (partial credit allowed)
- Reasoning quality
- Lenience for STT artifacts (homophones, dropped articles)

Return JSON ONLY:
{
  "score": 0.0-1.0,
  "is_correct": true|false,        // true if score >= 0.6
  "confidence": 0.0-1.0,
  "feedback": "one short sentence the student will hear",
  "missed_keywords": ["..."]
}
"""


async def scoring_node(state: KODMODState) -> dict[str, Any]:
    """Evaluate state['student_answer'] against state['quiz_question']."""
    question = state.get("quiz_question", {})
    student_answer = (state.get("student_answer") or state.get("user_input", "")).strip()
    expected = (question.get("expected_answer") or "").strip()
    qtype = question.get("type", "spoken")
    rubric = question.get("rubric", {})

    if not student_answer:
        return _empty_attempt(state, reason="no answer captured")

    # ---- Path 1: MCQ → exact letter match -------------------------------
    if qtype == "mcq":
        score, feedback = _score_mcq(student_answer, expected, question.get("options", []))
        attempt = _build_attempt(question, student_answer, score, feedback)
        return _emit(state, attempt)

    # ---- Path 2: Short factual → semantic similarity --------------------
    if qtype == "spoken":
        sim = await _semantic_similarity(student_answer, expected)
        # Convert similarity to score with a small floor for "close enough"
        score = float(np.clip((sim - 0.3) / 0.6, 0.0, 1.0))
        feedback = (
            "Tepat sekali!" if score >= 0.85
            else "Hampir benar, mari kita perjelas."
            if score >= 0.5
            else "Belum tepat. Tidak apa-apa, kita coba pelajari lagi."
        )
        attempt = _build_attempt(question, student_answer, score, feedback)
        return _emit(state, attempt)

    # ---- Path 3: Explanation / reasoning → LLM rubric ---------------------
    return await _score_with_rubric(state, question, student_answer, expected, rubric)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def _score_mcq(student_answer: str, expected: str, options: list[str]) -> tuple[float, str]:
    s = student_answer.lower().strip().rstrip(".!?")
    e = expected.lower().strip().rstrip(".!?")
    # Accept "A", "a", "jawaban A", or the full option text
    if s == e or s.endswith(e) or s.startswith(e[:1] + " ") or s == e[:1]:
        return 1.0, "Benar."
    # Substring match against the correct option text
    for opt in options:
        if opt.lower().startswith(e[:1].lower() + ".") and opt.lower() in s:
            return 1.0, "Benar."
    return 0.0, "Belum tepat."


async def _semantic_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    va, vb = await embed_text([a, b])
    va, vb = np.asarray(va), np.asarray(vb)
    cos = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))
    return cos


async def _score_with_rubric(
    state: KODMODState, question: dict, student_answer: str, expected: str, rubric: dict
) -> dict[str, Any]:
    import json
    llm = get_scoring_llm()
    payload = (
        f"Question: {question.get('text','')}\n"
        f"Expected: {expected}\n"
        f"Rubric: {json.dumps(rubric, ensure_ascii=False)}\n"
        f"Student answer (from speech): {student_answer}"
    )
    response = await llm.ainvoke(
        [
            {"role": "system", "content": RUBRIC_PROMPT},
            {"role": "user", "content": payload},
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Rubric JSON parse failed; defaulting to 0.0")
        result = {"score": 0.0, "is_correct": False, "confidence": 0.3,
                  "feedback": "Maaf, sistem belum bisa menilai jawaban itu.", "missed_keywords": []}

    attempt = _build_attempt(
        question,
        student_answer,
        float(result.get("score", 0.0)),
        result.get("feedback", ""),
        confidence=float(result.get("confidence", 0.7)),
        missed=result.get("missed_keywords", []),
    )
    return _emit(state, attempt)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _build_attempt(
    question: dict,
    student_answer: str,
    score: float,
    feedback: str,
    confidence: float = 0.9,
    missed: list[str] | None = None,
) -> QuizAttempt:
    return QuizAttempt(
        question_id=question.get("question_id", ""),
        student_answer=student_answer,
        score=score,
        is_correct=score >= 0.6,
        confidence=confidence,
        response_latency_ms=0,  # filled in by API layer
        feedback=feedback,
    )


def _empty_attempt(state: KODMODState, reason: str) -> dict[str, Any]:
    log.warning("Scoring skipped: %s", reason)
    return {
        "quiz_score": 0.0,
        "next_action": "analyze_quiz",
        "last_node": "scoring",
    }


def _emit(state: KODMODState, attempt: QuizAttempt) -> dict[str, Any]:
    attempts = list(state.get("quiz_attempts", [])) + [attempt]
    cumulative = sum(a["score"] for a in attempts) / max(len(attempts), 1)
    log.info("Scored attempt: %.2f (cumulative %.2f, n=%d)",
             attempt["score"], cumulative, len(attempts))
    return {
        "quiz_attempts": attempts,
        "quiz_score": attempt["score"],
        "cumulative_quiz_score": cumulative,
        "generated_response": attempt["feedback"],
        "next_action": "analyze_quiz",
        "last_node": "scoring",
    }
