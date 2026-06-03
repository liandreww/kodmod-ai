"""
KODMOD AI — Recommendation Agent
=================================

Sits at the end of the Analytics cluster. Translates raw analytics into
concrete, actionable next steps spoken to the student (and surfaced on the
teacher dashboard).

Recommendations always come in three flavors:

1. **Next lesson** — what to learn NOW, based on weak concepts + prerequisites.
2. **Practice exercise** — a Content cluster handle the system can call
   directly.
3. **Habit nudge** — encouragement / pacing advice keyed to engagement_index
   and streak_days.

The agent is intentionally conservative: it suggests at most 3 actions per
turn so the audio output stays digestible.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from graphs.state import KODMODState
from tools.llm_client import get_recommendation_llm
from tools.rag_tool import RAGTool

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are KODMOD's Recommendation Agent. Given a student's analytics summary,
produce 1 to 3 concrete next-step recommendations that will be SPOKEN to a
visually impaired student.

CONSTRAINTS
- Each recommendation: ≤ 18 spoken words.
- Mix: at most one "next lesson", at most one "practice exercise", at most
  one "habit nudge".
- Use second person ("kamu" in Indonesian, "you" in English).
- Friendly, never demanding. Acknowledge effort.

OUTPUT — JSON ONLY:
{
  "recommendations": [
    {"type": "next_lesson|practice|habit", "text": "...", "concept_id": "..."},
    ...
  ],
  "spoken_intro": "1 short sentence to lead into the list"
}
"""


async def recommendation_node(state: KODMODState) -> dict[str, Any]:
    summary = state.get("analytics_summary", {})
    profile = state.get("learning_profile", {})
    language = profile.get("language", "id")

    user_block = (
        f"Language: {language}\n"
        f"Analytics: {json.dumps(summary, ensure_ascii=False)}\n"
        f"Recent emotional state: {state.get('emotional_state','neutral')}\n"
        f"Misconceptions: {state.get('misconceptions_detected', [])}\n"
    )

    llm = get_recommendation_llm()
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
        log.warning("Recommendation JSON parse failed; using fallback")
        parsed = _fallback(summary)

    recs = parsed.get("recommendations", [])
    intro = parsed.get("spoken_intro", "Inilah rekomendasi untukmu.")

    spoken = intro + " " + " ".join(
        f"{i+1}. {r['text']}" for i, r in enumerate(recs)
    )

    log.info("Generated %d recommendations", len(recs))

    return {
        "recommendations": [r.get("text", "") for r in recs],
        "analytics_summary": {
            **summary,
            "structured_recommendations": recs,
        },
        "generated_response": (
            (state.get("generated_response", "") + " " + spoken).strip()
        ),
        "next_action": "accessibility_polish",
        "last_node": "recommendation",
    }


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _fallback(summary: dict) -> dict:
    weak = summary.get("weak_concepts", [])
    if weak:
        return {
            "recommendations": [
                {
                    "type": "practice",
                    "text": f"Lanjutkan dengan beberapa latihan singkat tentang {weak[0]}.",
                    "concept_id": weak[0],
                }
            ],
            "spoken_intro": "Saran cepat untukmu:",
        }
    return {
        "recommendations": [
            {"type": "habit", "text": "Pertahankan ritme belajarmu hari ini.", "concept_id": ""},
        ],
        "spoken_intro": "Kerja bagus.",
    }
