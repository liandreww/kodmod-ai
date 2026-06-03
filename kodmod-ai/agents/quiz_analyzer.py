"""
KODMOD AI — Quiz Analyzer Agent
================================

Runs after the Scoring Agent. Looks at the full set of quiz attempts in the
current session and produces:

* Detected misconceptions (linked to concept IDs in the curriculum graph)
* Per-concept weakness scores
* A short, audio-friendly summary that the Hasil Analisis → TTS path will
  speak back to the student (matches the Quiz/Assessment cluster diagram).
* Remediation recommendations passed to the recommendation_agent later.

This agent does NOT write to the database directly — that's the
`update_student_model` node's job. Analyzer only enriches state.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from graphs.state import KODMODState
from tools.llm_client import get_scoring_llm

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are KODMOD's Quiz Analyzer. Given a student's set of attempts on a quiz,
identify:

1. Misconceptions — wrong-but-systematic patterns (e.g. "always adds when
   should multiply", "confuses cause and correlation").
2. Weak concepts — concept_ids where the student struggled.
3. Strong concepts — concept_ids where the student excelled.
4. Remediation suggestions — 1–3 short actions the tutor can take next.

The student is visually impaired. The summary will be SPOKEN to them.

Return JSON ONLY:
{
  "misconceptions": ["short label", ...],
  "weak_concepts":   ["concept_id", ...],
  "strong_concepts": ["concept_id", ...],
  "remediation":     ["action 1", "action 2"],
  "spoken_summary":  "2-3 friendly sentences for the student to hear",
  "teacher_summary": "more technical 1-2 sentences for the teacher dashboard"
}
"""


async def quiz_analyzer_node(state: KODMODState) -> dict[str, Any]:
    """Synthesize learning insights from the completed (or in-progress) quiz."""
    attempts = state.get("quiz_attempts", [])
    questions = state.get("quiz_questions", [])

    if not attempts:
        return {
            "next_action": "update_student_model",
            "last_node": "quiz_analyzer",
        }

    # ---- Pre-compute deterministic stats so the LLM doesn't have to ------
    by_concept: dict[str, list[float]] = defaultdict(list)
    q_by_id = {q.get("question_id"): q for q in questions}
    for a in attempts:
        q = q_by_id.get(a.get("question_id"), {})
        cid = q.get("concept_id", "unknown")
        by_concept[cid].append(a.get("score", 0.0))

    concept_avg = {cid: sum(s) / len(s) for cid, s in by_concept.items()}

    # ---- Build a compact dossier for the LLM ----------------------------
    dossier_lines = []
    for a in attempts:
        q = q_by_id.get(a.get("question_id"), {})
        dossier_lines.append(
            f"- concept={q.get('concept_id','?')} "
            f"q='{q.get('text','')[:80]}' "
            f"answer='{a.get('student_answer','')[:80]}' "
            f"score={a.get('score',0):.2f} "
            f"correct={a.get('is_correct', False)}"
        )
    dossier = "\n".join(dossier_lines)

    user_block = (
        f"Concept averages: {json.dumps(concept_avg)}\n\n"
        f"Attempts:\n{dossier}"
    )

    llm = get_scoring_llm()
    response = await llm.ainvoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ]
    )
    raw = response.content if hasattr(response, "content") else str(response)

    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        analysis = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Analyzer JSON parse failed; using defaults")
        analysis = {
            "misconceptions": [],
            "weak_concepts": [c for c, s in concept_avg.items() if s < 0.6],
            "strong_concepts": [c for c, s in concept_avg.items() if s >= 0.8],
            "remediation": ["Tinjau kembali konsep yang lemah."],
            "spoken_summary": (
                "Kuis selesai. Mari kita tinjau bagian yang masih perlu latihan."
            ),
            "teacher_summary": "Analyzer fallback — see raw concept averages.",
        }

    log.info(
        "Quiz analyzed: %d attempts, %d weak concepts, %d misconceptions",
        len(attempts),
        len(analysis.get("weak_concepts", [])),
        len(analysis.get("misconceptions", [])),
    )

    return {
        "misconceptions_detected": analysis.get("misconceptions", []),
        "analytics_summary": {
            **state.get("analytics_summary", {}),
            "weak_concepts": analysis.get("weak_concepts", []),
            "strong_concepts": analysis.get("strong_concepts", []),
            "concept_averages": concept_avg,
            "teacher_summary": analysis.get("teacher_summary", ""),
        },
        "recommendations": analysis.get("remediation", []),
        "generated_response": analysis.get("spoken_summary", ""),
        "next_action": "update_student_model",
        "last_node": "quiz_analyzer",
    }
