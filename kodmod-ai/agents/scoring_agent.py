"""
KODMOD AI — Scoring Agent
=========================

Evaluates a student's answer to a quiz question. Combines two signals:

1. **Exact match** — for MCQ: the letter (or option text) either matches the
   canonical answer or it doesn't.
2. **LLM rubric grading** — for every other question type (`spoken`,
   `explain`, `reasoning`, `step_by_step`), an LLM applies the rubric stored
   on the question. This tolerates paraphrasing and speech-recognition
   artifacts far better than a bare embedding-similarity threshold would —
   important because the problem generator does not always label a question
   type consistently with what it actually demands (e.g. an explanation
   question tagged `"spoken"`), and a strict similarity cutoff against a
   terse canonical answer would then unfairly fail a genuinely correct,
   differently-worded response.

Outputs a `QuizAttempt` appended to `state["quiz_attempts"]` and updates
`state["quiz_score"]` with the score for THIS attempt (0.0–1.0). Also mirrors
progress (including the per-question retry count) into Redis on every call —
not just on a pass — so a remediation retry is not lost between turns; see
`route_after_scoring` / `QUIZ_MAX_ATTEMPTS_PER_QUESTION` in `graphs/main_graph.py`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from config.settings import settings
from graphs.state import KODMODState, QuizAttempt, QuizQuestion
from tools.llm_client import get_scoring_llm, language_instruction

log = logging.getLogger(__name__)


RUBRIC_PROMPT = """\
You are a strict but fair grader for spoken student answers.

Given:
- The question
- The expected answer
- The rubric (criteria + keywords)
- The student's answer (often transcribed from speech, so it may contain
  recognition errors)

Score 0.0–1.0 considering:
- Correctness of the core idea
- Coverage of rubric keywords (partial credit allowed)
- Reasoning quality
- Lenience for speech-recognition artifacts (homophones, dropped articles)

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
        return await _empty_attempt(state, reason="no answer captured")

    # ---- Path 1: MCQ → exact letter match, else rubric grading -----------
    if qtype == "mcq":
        options = question.get("options", [])
        score, feedback = _score_mcq(student_answer, expected, options)
        if score is not None:
            attempt = _build_attempt(question, student_answer, score, feedback)
            return await _emit(state, attempt)
        # No leading letter and no same-language option match — e.g. the
        # student restated the correct option's content in a different
        # language than the options were generated in. Don't default this to
        # wrong; judge it against the correct option's full text instead.
        correct_option = _find_option_text(options, expected) or expected
        return await _score_with_rubric(state, question, student_answer, correct_option, rubric)

    # ---- Path 2: everything else → LLM rubric grading --------------------
    return await _score_with_rubric(state, question, student_answer, expected, rubric)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_MCQ_LEADING_LETTER = re.compile(r"^\s*([a-dA-D])\b")


def _score_mcq(
    student_answer: str, expected: str, options: list[str]
) -> tuple[float | None, str]:
    """Grade an MCQ answer. Returns ``(None, "")`` when the answer's shape is
    genuinely ambiguous, so the caller can fall back to LLM rubric grading
    instead of defaulting to wrong.
    """
    s = student_answer.strip()
    e = expected.strip().rstrip(".!?")
    if not e:
        # No canonical answer to match against — never award credit blindly.
        return 0.0, "Belum tepat."

    # Confident case: the answer leads with an option letter. Any punctuation
    # or restated text may follow — "B", "B.", "B, dua per empat" all count,
    # since the word boundary after the letter doesn't require a space.
    m = _MCQ_LEADING_LETTER.match(s)
    if m:
        correct = m.group(1).lower() == e[:1].lower()
        return (1.0, "Benar.") if correct else (0.0, "Belum tepat.")

    # No leading letter — maybe they restated the option text verbatim, in
    # the same language the options were generated in.
    s_lower = s.lower().rstrip(".!?")
    e_lower = e.lower()
    if s_lower == e_lower:
        return 1.0, "Benar."
    for opt in options:
        if opt.lower().startswith(e_lower[:1] + ".") and opt.lower() in s_lower:
            return 1.0, "Benar."

    # Inconclusive from string shape alone.
    return None, ""


def _find_option_text(options: list[str], expected_letter: str) -> str | None:
    """The full text of the option matching `expected_letter` (e.g. "B. ...")."""
    letter = expected_letter.strip()[:1].lower()
    if not letter:
        return None
    for opt in options:
        if opt.strip().lower().startswith(f"{letter}."):
            return opt
    return None


async def _score_with_rubric(
    state: KODMODState,
    question: QuizQuestion | dict[str, Any],
    student_answer: str,
    expected: str,
    rubric: dict,
) -> dict[str, Any]:
    import json

    llm = get_scoring_llm()
    payload = (
        f"Question: {question.get('text', '')}\n"
        f"Expected: {expected}\n"
        f"Rubric: {json.dumps(rubric, ensure_ascii=False)}\n"
        f"Student answer (from speech): {student_answer}"
    )
    response = await llm.ainvoke(
        [
            {"role": "system", "content": RUBRIC_PROMPT + language_instruction()},
            {"role": "user", "content": payload},
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)
    try:
        cleaned = (
            raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Rubric JSON parse failed; defaulting to 0.0")
        result = {
            "score": 0.0,
            "is_correct": False,
            "confidence": 0.3,
            "feedback": "Maaf, sistem belum bisa menilai jawaban itu.",
            "missed_keywords": [],
        }

    attempt = _build_attempt(
        question,
        student_answer,
        float(result.get("score", 0.0)),
        result.get("feedback", ""),
        confidence=float(result.get("confidence", 0.7)),
        missed=result.get("missed_keywords", []),
    )
    return await _emit(state, attempt)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _build_attempt(
    question: QuizQuestion | dict[str, Any],
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


async def _empty_attempt(state: KODMODState, reason: str) -> dict[str, Any]:
    log.warning("Scoring skipped: %s", reason)
    question_attempts = state.get("current_question_attempts", 0) + 1
    await _persist_progress(
        state,
        state.get("quiz_attempts", []),
        question_attempts,
        state.get("cumulative_quiz_score", 0.0),
    )
    return {
        "quiz_score": 0.0,
        "current_question_attempts": question_attempts,
        "next_action": "analyze_quiz",
        "last_node": "scoring",
    }


async def _emit(state: KODMODState, attempt: QuizAttempt) -> dict[str, Any]:
    question_attempts = state.get("current_question_attempts", 0) + 1

    # Still wrong on the last allowed try: route_after_scoring is about to
    # force the quiz onward regardless of score, so say that plainly instead
    # of the grader's normal wrong-answer feedback, which would otherwise
    # invite a retry that isn't coming.
    if (
        attempt["score"] < settings.QUIZ_PASS_THRESHOLD
        and question_attempts >= settings.QUIZ_MAX_ATTEMPTS_PER_QUESTION
    ):
        attempt = {**attempt, "feedback": "Tidak apa-apa, kita lanjut ke soal berikutnya."}

    attempts = [*state.get("quiz_attempts", []), attempt]
    cumulative = sum(a["score"] for a in attempts) / max(len(attempts), 1)
    log.info(
        "Scored attempt: %.2f (cumulative %.2f, n=%d, question_attempts=%d)",
        attempt["score"],
        cumulative,
        len(attempts),
        question_attempts,
    )
    await _persist_progress(state, attempts, question_attempts, cumulative)
    return {
        "quiz_attempts": attempts,
        "quiz_score": attempt["score"],
        "cumulative_quiz_score": cumulative,
        "current_question_attempts": question_attempts,
        "generated_response": attempt["feedback"],
        "next_action": "analyze_quiz",
        "last_node": "scoring",
    }


async def _persist_progress(
    state: KODMODState,
    attempts: list[QuizAttempt],
    question_attempts: int,
    cumulative: float,
) -> None:
    """Mirror this attempt into Redis, pass or fail.

    Previously only `update_student_model_node` persisted quiz progress, and
    only on a pass — so a low-scoring (remediation) retry vanished on the next
    turn and the per-question attempt count could never be enforced. This is
    what lets `route_after_scoring` force the quiz to advance after
    `settings.QUIZ_MAX_ATTEMPTS_PER_QUESTION` failed tries instead of looping
    on the same question forever.
    """
    session_id = state.get("session_id")
    if not session_id:
        return
    try:
        from memory.short_term import store_quiz_session

        await store_quiz_session(
            session_id,
            {
                "quiz_session_id": state.get("quiz_session_id", ""),
                "quiz_questions": state.get("quiz_questions", []),
                "current_question_index": state.get("current_question_index", 0),
                "current_question_attempts": question_attempts,
                "quiz_question": state.get("quiz_question", {}),
                "quiz_attempts": attempts,
                "cumulative_quiz_score": cumulative,
            },
        )
    except Exception:  # pragma: no cover - Redis best-effort
        log.warning("Could not persist quiz progress to short-term memory", exc_info=True)
