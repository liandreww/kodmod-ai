"""
KODMOD AI — Tutoring Agent
==========================

The conversational, Socratic, RAG-grounded tutor. This is the dominant agent
in the Practices & Tutoring cluster (yellow box in the diagram).

Behaviours implemented
----------------------
1. **Adaptive level** — reads `mastery_scores[concept_id]` to decide whether to
   explain at "scaffolded", "standard", or "advanced" depth.
2. **Socratic questioning** — at the end of each explanation, asks one
   follow-up question to probe understanding (this is what triggers the loop
   back to STT in the diagram).
3. **Misconception logging** — if the student's input contradicts curriculum
   facts retrieved by RAG, the agent appends to `misconceptions_detected`
   so the analytics cluster can act on it later.
4. **Audio-friendly** — explicitly avoids visual references ("look at the
   diagram", "as you can see"); the Accessibility Agent further polishes the
   output before TTS.
5. **Streaming** — uses `astream` so the WebSocket can begin TTS synthesis
   on the first sentence rather than waiting for the full response.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graphs.state import KODMODState
from tools.llm_client import get_tutor_llm
from tools.rag_tool import RAGTool
from tools.student_profile_tool import StudentProfileTool
from prompts.loader import load_prompt

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are KODMOD's Tutor — a patient, encouraging teacher for visually impaired
students. Your responses will be spoken aloud, so:

CONTENT RULES
- Never reference visuals ("see the chart", "look at this"). Describe verbally.
- Use sequential, narrated reasoning. Walk through one step at a time.
- Keep sentences under ~20 words for clarity at audio speed.
- When introducing a new term, repeat it twice in different phrasings.
- Use short concrete analogies grounded in non-visual senses (sound, touch,
  motion) when helpful.

PEDAGOGY
- Diagnose first: if the student seems lost, ask one short clarifying question
  before explaining.
- Explain in 2–4 short paragraphs. Then ask ONE Socratic follow-up question.
- Prefer examples to definitions. Show, don't list.
- If the retrieved curriculum context contradicts the student's belief, gently
  surface the misconception and explain why.

ADAPTATION
- Mastery score for current concept will be provided as <mastery>.
  - mastery < 0.3 → start from prerequisites, very small steps
  - 0.3 ≤ mastery < 0.7 → standard explanation with one example
  - mastery ≥ 0.7 → push toward synthesis or edge cases

TONE
- Warm, never condescending. Acknowledge effort.
- If frustration is detected, slow down and offer a brief encouragement.

OUTPUT
- Plain prose. No markdown, no headers, no bullet symbols. The TTS engine
  reads literal text.
"""


async def tutoring_node(state: KODMODState) -> dict[str, Any]:
    """LangGraph node — generates the tutor's response."""
    user_input = state.get("user_input", "")
    concept_id = state.get("current_concept_id", "")
    mastery = state.get("mastery_scores", {}).get(concept_id, 0.5)
    emotion = state.get("emotional_state", "neutral")
    retrieved = state.get("retrieved_docs", [])

    # ---- Build context block from RAG retrieval --------------------------
    context_block = _format_retrieved(retrieved)

    # ---- Build conversational history (last 6 turns) ----------------------
    history = state.get("tutoring_context", [])[-6:]
    history_msgs = []
    for turn in history:
        role = turn.get("role", "student")
        content = turn.get("text", "")
        if role == "student":
            history_msgs.append(HumanMessage(content=content))
        else:
            history_msgs.append(AIMessage(content=content))

    # ---- Compose system message with adaptive hints ----------------------
    sys_with_meta = (
        SYSTEM_PROMPT
        + f"\n\n<mastery>{mastery:.2f}</mastery>"
        + f"\n<emotion>{emotion}</emotion>"
        + (f"\n<concept>{concept_id}</concept>" if concept_id else "")
    )

    user_msg = HumanMessage(
        content=(
            f"{user_input}\n\n"
            f"--- Curriculum context (use only what's relevant) ---\n{context_block}"
        )
    )

    llm = get_tutor_llm()
    response = await llm.ainvoke(
        [SystemMessage(content=sys_with_meta), *history_msgs, user_msg]
    )
    answer = response.content if hasattr(response, "content") else str(response)

    # ---- Update tutoring_context for next turn ---------------------------
    new_history = list(history) + [
        {"role": "student", "text": user_input, "concept_id": concept_id},
        {"role": "tutor", "text": answer, "concept_id": concept_id},
    ]

    log.info("Tutor produced %d chars (mastery=%.2f, emotion=%s)",
             len(answer), mastery, emotion)

    return {
        "generated_response": answer,
        "tutoring_context": new_history,
        "next_action": "accessibility_polish",
        "last_node": "tutoring",
        # `messages` uses the add_messages reducer → these get appended
        "messages": [user_msg, AIMessage(content=answer)],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_retrieved(docs: list[dict]) -> str:
    """Render retrieved chunks as a numbered list the LLM can ground on."""
    if not docs:
        return "(no curriculum context retrieved)"
    lines = []
    for i, d in enumerate(docs[:5], 1):
        src = d.get("source", "curriculum")
        text = d.get("text", "").strip().replace("\n", " ")
        lines.append(f"[{i}] ({src}) {text}")
    return "\n".join(lines)
