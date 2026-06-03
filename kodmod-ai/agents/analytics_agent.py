"""
KODMOD AI — Learning Analytics Agent
=====================================

The central node of the **Analytics & Reporting cluster** (Image 1). Reads from
the database (long-term memory) plus current-session state, computes
performance metrics, and prepares two output products:

* `analytics_summary` in state — used by the Recommendation Agent and (after
  TTS) read aloud to the student.
* Persistent rows in `analytics_reports` — surfaced on the Student Dashboard
  and Teacher Dashboard.

Metrics computed
----------------
- Overall mastery (mean of per-concept scores)
- Top 3 weak concepts and top 3 strong concepts
- Streak days (consecutive active days)
- Total sessions / total quizzes
- Average quiz score
- Engagement index (composite of session frequency, quiz completion rate,
  voice interaction quality)
- Trend deltas vs. last 7 / 30 days
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from analytics.aggregator import StudentAggregator
from analytics.insights import generate_insights
from graphs.state import AnalyticsSummary, KODMODState

log = logging.getLogger(__name__)


async def analytics_node(state: KODMODState) -> dict[str, Any]:
    """Compute analytics for the current student and update state."""
    student_id = state.get("student_id")
    if not student_id:
        log.warning("Analytics called without student_id")
        return {"next_action": "recommend", "last_node": "analytics"}

    aggregator = StudentAggregator(student_id=student_id)
    raw = await aggregator.compute(window_days=30)

    insights = await generate_insights(raw)

    summary: AnalyticsSummary = {
        "overall_mastery": raw["overall_mastery"],
        "weak_concepts": raw["weak_concepts"][:3],
        "strong_concepts": raw["strong_concepts"][:3],
        "streak_days": raw["streak_days"],
        "sessions_total": raw["sessions_total"],
        "avg_quiz_score": raw["avg_quiz_score"],
        "engagement_index": raw["engagement_index"],
        "recommendations": insights.get("recommendations", []),
    }

    # Audio-friendly summary the TTS will speak if the student requested
    # analytics via the Intent Router
    spoken = _spoken_summary(summary)

    log.info(
        "Analytics for %s: mastery=%.2f sessions=%d engagement=%.2f",
        student_id, summary["overall_mastery"], summary["sessions_total"],
        summary["engagement_index"],
    )

    # Persist to the analytics_reports table (fire-and-forget)
    await aggregator.persist(summary)

    return {
        "analytics_summary": {**state.get("analytics_summary", {}), **summary},
        "generated_response": spoken,
        "next_action": "recommend",
        "last_node": "analytics",
    }


# ---------------------------------------------------------------------------
# Spoken summary builder
# ---------------------------------------------------------------------------

def _spoken_summary(s: AnalyticsSummary) -> str:
    """Render analytics as 3–4 sentences friendly to TTS playback."""
    mastery_pct = round(s.get("overall_mastery", 0.0) * 100)
    streak = s.get("streak_days", 0)
    sessions = s.get("sessions_total", 0)
    weak = s.get("weak_concepts", [])
    strong = s.get("strong_concepts", [])

    parts = [
        f"Sejauh ini penguasaan keseluruhanmu sekitar {mastery_pct} persen.",
        (
            f"Kamu sudah belajar selama {streak} hari beruntun"
            f" dengan total {sessions} sesi."
            if streak > 1 else
            f"Total kamu sudah menjalani {sessions} sesi belajar."
        ),
    ]
    if strong:
        parts.append(
            f"Topik terkuatmu saat ini adalah {strong[0]}"
            + (f" dan {strong[1]}." if len(strong) > 1 else ".")
        )
    if weak:
        parts.append(
            f"Yang masih perlu kita perdalam: {weak[0]}"
            + (f", {weak[1]}." if len(weak) > 1 else ".")
        )
    return " ".join(parts)
