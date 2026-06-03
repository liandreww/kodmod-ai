"""
KODMOD AI — Quiz Agent (and Mini-Quiz)
=======================================

Implements two related but distinct nodes:

1. `quiz_node` — full quiz session driver from the **Quiz/Assessment cluster**.
   Asks the next question in `state["quiz_questions"]`, manages pacing,
   handles repeat / clarify side-requests.

2. `mini_quiz_node` — the lightweight quick-check inside the **Practices &
   Tutoring cluster** (the "Mini quiz" box in the Practices diagram).
   Generates a single on-the-fly check question after a tutoring explanation.

Both are designed for spoken delivery: questions are phrased to be
unambiguous when heard once, and never reference visuals.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from graphs.state import KODMODState, QuizQuestion
from tools.llm_client import get_quiz_llm
from tools.rag_tool import RAGTool

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. FULL QUIZ NODE
# ---------------------------------------------------------------------------

ASK_PROMPT = """\
You are the Quiz Host for KODMOD AI. The student is visually impaired and
will hear this question via TTS.

Rules for spoken questions:
- One sentence stem, then options (if MCQ) prefixed by 'A,', 'B,', 'C,', 'D,'.
- No visual references.
- Numbers spoken in words for amounts under 20.
- For 'spoken' / 'explain' / 'reasoning' question types, do NOT list options —
  just ask the question and a brief framing like "explain in your own words".
- Always end with a clear closing prompt like "What's your answer?" or
  "Take your time."

Output ONLY the question text to be spoken. No prefixes, no JSON.
"""


async def quiz_node(state: KODMODState) -> dict[str, Any]:
    """Ask the next question in the quiz session."""
    questions = state.get("quiz_questions", [])
    idx = state.get("current_question_index", 0)

    if not questions or idx >= len(questions):
        log.info("Quiz session has no more questions")
        return {
            "generated_response": (
                "Bagus! Kuis ini sudah selesai. Mari kita lihat hasilnya bersama."
            ),
            "next_action": "analyze_quiz",
            "last_node": "quiz_ask",
        }

    q: QuizQuestion = questions[idx]
    question_number = idx + 1
    total = len(questions)

    # Render the question through the LLM so options/phrasing are spoken-friendly
    raw_q = q.get("text", "")
    options = q.get("options", []) or []
    qtype = q.get("type", "spoken")

    user_block = (
        f"Question {question_number} of {total}.\n"
        f"Type: {qtype}\n"
        f"Stem: {raw_q}\n"
        f"Options: {options if options else 'none'}"
    )

    llm = get_quiz_llm()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": ASK_PROMPT},
            {"role": "user", "content": user_block},
        ]
    )
    spoken_question = response.content if hasattr(response, "content") else str(response)

    # Prepend a tiny intro for the FIRST question of the session
    if idx == 0:
        spoken_question = (
            f"Baik, kita mulai kuis. Ada {total} soal. Soal pertama: "
            + spoken_question
        )

    log.info("Asking question %d/%d (concept=%s, difficulty=%s)",
             question_number, total, q.get("concept_id"), q.get("difficulty"))

    return {
        "quiz_question": q,
        "generated_response": spoken_question,
        "next_action": "speak",
        "last_node": "quiz_ask",
    }


# ---------------------------------------------------------------------------
# 2. MINI-QUIZ NODE  (inside Practices & Tutoring cluster)
# ---------------------------------------------------------------------------

MINI_PROMPT = """\
You are KODMOD's Mini-Quiz generator. After a short tutoring explanation,
generate ONE quick check question to verify the student understood the key
idea. Constraints:

- Must be answerable in one sentence or one number/word.
- Spoken, no visuals.
- Difficulty matches the just-explained concept.
- Do NOT reuse phrasing from the explanation verbatim — test understanding,
  not memory.

Output JSON ONLY:
{
  "text": "the question to ask",
  "type": "spoken" | "mcq",
  "options": [],            // empty if not mcq
  "expected_answer": "the canonical answer",
  "rubric": {"keywords": ["..."]}
}
"""


async def mini_quiz_node(state: KODMODState) -> dict[str, Any]:
    """Generate a single quick-check question after a tutoring explanation."""
    last_explanation = state.get("generated_response", "")
    concept_id = state.get("current_concept_id", "")

    llm = get_quiz_llm()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": MINI_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Concept: {concept_id}\n"
                    f"Tutor's explanation just given:\n---\n{last_explanation}\n---"
                ),
            },
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)

    import json
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Mini-quiz JSON parse failed; skipping mini-quiz")
        return {"next_action": "speak", "last_node": "mini_quiz"}

    question: QuizQuestion = {
        "question_id": str(uuid4()),
        "text": parsed.get("text", ""),
        "type": parsed.get("type", "spoken"),
        "options": parsed.get("options", []),
        "expected_answer": parsed.get("expected_answer", ""),
        "rubric": parsed.get("rubric", {}),
        "concept_id": concept_id,
        "difficulty": state.get("current_difficulty", "medium"),
    }

    log.info("Mini-quiz generated: %s", question["text"][:60])
    return {
        "quiz_question": question,
        "quiz_questions": [question],
        "current_question_index": 0,
        "quiz_session_id": f"mini-{uuid4().hex[:8]}",
        "generated_response": (
            f"Cek pemahaman cepat: {question['text']}"
        ),
        "next_action": "speak",
        "last_node": "mini_quiz",
    }
