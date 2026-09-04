"""
KODMOD AI — Student Model
==========================

The persistent representation of what a student knows. Implements a
lightweight version of Bayesian Knowledge Tracing (BKT) for each concept:

    P(L_t) = P(L_{t-1} | evidence)
    P(L_t) = P(L_t)(1 − P(slip)) + (1 − P(L_t))P(guess)        # for predictions

For KODMOD we don't need a full BKT — a moving-average with confidence
weighting is faster and easier to interpret. We expose:

* `update(concept_id, score, confidence)` — call after every quiz attempt
* `mastery_scores()` — full dict for the LangGraph state
* `weak_concepts(n)` / `strong_concepts(n)` — for analytics + recommendations
* `velocity(concept_id, days)` — change in mastery over a window
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from database.session import async_session

log = logging.getLogger(__name__)


# Tunable: how strongly each new attempt nudges mastery
LEARNING_RATE = 0.25
# Decay applied per day of inactivity (forgetting curve, very mild)
DAILY_DECAY = 0.005


@dataclass
class StudentModel:
    student_id: str
    _scores: dict[str, float] = field(default_factory=dict)
    _confidence: dict[str, float] = field(default_factory=dict)
    _attempts: dict[str, int] = field(default_factory=dict)
    _last_practiced: dict[str, datetime] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Loading & saving
    # ------------------------------------------------------------------
    @classmethod
    async def load(cls, student_id: str) -> StudentModel:
        m = cls(student_id=student_id)
        async with async_session() as s:
            rows = await s.execute(
                text(
                    "SELECT concept_id, mastery AS score, confidence, n_attempts, "
                    "last_seen AS last_practiced "
                    "FROM mastery_scores WHERE student_id = CAST(:sid AS uuid)"
                ),
                {"sid": str(student_id)},
            )
            for r in rows:
                cid = str(r.concept_id)
                m._scores[cid] = float(r.score)
                m._confidence[cid] = float(r.confidence)
                m._attempts[cid] = int(r.n_attempts)
                if r.last_practiced:
                    m._last_practiced[cid] = r.last_practiced
        return m

    async def persist(self) -> None:
        async with async_session() as s:
            for cid, score in self._scores.items():
                await s.execute(
                    text(
                        """
                        INSERT INTO mastery_scores
                            (id, student_id, concept_id, mastery, confidence,
                             n_attempts, last_seen)
                        VALUES (gen_random_uuid(), CAST(:sid AS uuid),
                                CAST(:cid AS uuid), :sc, :cf, :n, :lp)
                        ON CONFLICT (student_id, concept_id) DO UPDATE
                          SET mastery = EXCLUDED.mastery,
                              confidence = EXCLUDED.confidence,
                              n_attempts = EXCLUDED.n_attempts,
                              last_seen = EXCLUDED.last_seen
                        """
                    ),
                    {
                        "sid": str(self.student_id),
                        "cid": str(cid),
                        "sc": score,
                        "cf": self._confidence.get(cid, 0.5),
                        "n": self._attempts.get(cid, 0),
                        "lp": self._last_practiced.get(cid, datetime.now(UTC)),
                    },
                )
            await s.commit()

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def update(self, concept_id: str, attempt_score: float, confidence: float = 0.9) -> None:
        prev = self._scores.get(concept_id, 0.5)
        # Weight by confidence — uncertain scores nudge less
        delta = (attempt_score - prev) * LEARNING_RATE * confidence
        new_score = max(0.0, min(1.0, prev + delta))
        # Confidence accumulates with attempts
        new_conf = min(1.0, self._confidence.get(concept_id, 0.5) + 0.05)

        self._scores[concept_id] = new_score
        self._confidence[concept_id] = new_conf
        self._attempts[concept_id] = self._attempts.get(concept_id, 0) + 1
        self._last_practiced[concept_id] = datetime.now(UTC)

        log.info(
            "Mastery update: student=%s concept=%s %.3f → %.3f (conf=%.2f)",
            self.student_id,
            concept_id,
            prev,
            new_score,
            new_conf,
        )

    def apply_decay(self) -> None:
        """Mild forgetting curve — call before reading scores for analytics."""
        now = datetime.now(UTC)
        for cid, last in self._last_practiced.items():
            days = max(0, (now - last).days)
            if days == 0:
                continue
            self._scores[cid] = max(0.0, self._scores[cid] - DAILY_DECAY * days)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    async def mastery_scores(self) -> dict[str, float]:
        return dict(self._scores)

    def weak_concepts(self, n: int = 3) -> list[str]:
        return [c for c, _ in sorted(self._scores.items(), key=lambda kv: kv[1])[:n]]

    def strong_concepts(self, n: int = 3) -> list[str]:
        return [c for c, _ in sorted(self._scores.items(), key=lambda kv: -kv[1])[:n]]

    def overall_mastery(self) -> float:
        if not self._scores:
            return 0.0
        return sum(self._scores.values()) / len(self._scores)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


async def update_student_model_node(state) -> dict[str, Any]:
    """Apply quiz_attempts to the persistent student model."""
    student_id = state.get("student_id")
    attempts = state.get("quiz_attempts", [])
    questions = state.get("quiz_questions", [])
    if not student_id or not attempts:
        return {"next_action": "generate_analytics", "last_node": "update_student_model"}

    model = await StudentModel.load(student_id)
    q_by_id = {q.get("question_id"): q for q in questions}
    for a in attempts:
        q = q_by_id.get(a.get("question_id"), {})
        cid = q.get("concept_id")
        if not cid:
            continue
        model.update(cid, float(a.get("score", 0.0)), confidence=float(a.get("confidence", 0.9)))

    await model.persist()

    # Advance the question index and mirror the progress into short-term
    # memory so the next utterance re-enters the graph on the right question.
    new_index = state.get("current_question_index", 0) + 1
    session_id = state.get("session_id")
    if session_id:
        try:
            from memory.short_term import clear_quiz_session, store_quiz_session

            if new_index >= len(questions):
                await clear_quiz_session(session_id)
            else:
                await store_quiz_session(
                    session_id,
                    {
                        "quiz_session_id": state.get("quiz_session_id", ""),
                        "quiz_questions": questions,
                        "current_question_index": new_index,
                        "quiz_question": questions[new_index],
                        "quiz_attempts": attempts,
                        "cumulative_quiz_score": state.get("cumulative_quiz_score", 0.0),
                    },
                )
        except Exception:  # pragma: no cover - Redis best-effort
            log.warning("Could not update quiz session in short-term memory", exc_info=True)

    return {
        "mastery_scores": await model.mastery_scores(),
        "current_question_index": new_index,
        "next_action": "generate_analytics",
        "last_node": "update_student_model",
    }
