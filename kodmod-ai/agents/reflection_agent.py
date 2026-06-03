"""
KODMOD AI — Reflection Agent
=============================

An optional but powerful self-correction layer. After the Tutoring Agent
emits an explanation, the Reflection Agent rapidly judges:

1. **Pedagogical quality** — does it scaffold? does it answer the actual
   question? is it grounded in the retrieved curriculum?
2. **Accessibility** — any visual references, formatting, or jargon left?
3. **Safety** — anything inappropriate for a minor learner?
4. **Hallucination check** — claims unsupported by `retrieved_docs`?

If the score is below threshold, the agent rewrites the response (or, when
running with a checkpointer, requests a human-in-the-loop review by raising
an interrupt).

Cost optimization
-----------------
* Uses the small/fast LLM (Haiku / Llama-3-8B / Mini).
* Skips entirely for low-stakes paths (mini-quiz, recommendations) — only
  runs after `tutoring_node`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from graphs.state import KODMODState
from tools.llm_client import get_router_llm  # small, fast model

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are KODMOD's Reflection Agent. You evaluate a tutor response BEFORE it
is spoken to a visually impaired student.

Score 0.0–1.0 on each axis:
- pedagogy:        does it scaffold + answer the question?
- accessibility:   no visual refs, no markdown, no jargon-heavy?
- groundedness:    consistent with curriculum_context (or honest about uncertainty)?
- safety:          appropriate for a school-age learner?

If overall_score < 0.7 OR any axis < 0.5, propose a rewrite.

OUTPUT — JSON ONLY:
{
  "pedagogy": 0-1,
  "accessibility": 0-1,
  "groundedness": 0-1,
  "safety": 0-1,
  "overall_score": 0-1,
  "needs_rewrite": true|false,
  "issues": ["..."],
  "rewritten": "the improved response, or empty string if not needed"
}
"""


async def reflection_node(state: KODMODState) -> dict[str, Any]:
    response = state.get("generated_response", "")
    user_input = state.get("user_input", "")
    docs = state.get("retrieved_docs", [])

    if not response.strip():
        return {"next_action": "accessibility_polish", "last_node": "reflection"}

    context_block = "\n".join(
        f"- {d.get('text','')[:200]}" for d in docs[:4]
    ) or "(none)"

    user_block = (
        f"Student question: {user_input}\n\n"
        f"Tutor response:\n{response}\n\n"
        f"Curriculum context:\n{context_block}"
    )

    llm = get_router_llm()
    raw_resp = await llm.ainvoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ]
    )
    raw = raw_resp.content if hasattr(raw_resp, "content") else str(raw_resp)

    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        verdict = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Reflection JSON parse failed; passing response through")
        return {"next_action": "accessibility_polish", "last_node": "reflection"}

    needs_rewrite = bool(verdict.get("needs_rewrite", False))
    overall = float(verdict.get("overall_score", 0.8))

    log.info("Reflection: overall=%.2f rewrite=%s issues=%s",
             overall, needs_rewrite, verdict.get("issues", []))

    out: dict[str, Any] = {
        "next_action": "accessibility_polish",
        "last_node": "reflection",
        "analytics_summary": {
            **state.get("analytics_summary", {}),
            "last_reflection_score": overall,
        },
    }

    if needs_rewrite:
        new_text = (verdict.get("rewritten") or "").strip()
        if new_text:
            out["generated_response"] = new_text
            log.info("Reflection rewrote tutor response")
        # If the issue is severe (overall < 0.4) and a checkpointer is
        # present, request human-in-the-loop:
        if overall < 0.4:
            out["interrupt_reason"] = "low-quality response flagged by reflection"

    return out
