"""
KODMOD AI — Insight Generation
==============================

Converts raw analytics rollups into:

1. A short, spoken-friendly summary in Bahasa Indonesia for the student.
2. Actionable insights for the teacher dashboard.
3. Suggestions consumed by the Recommendation Agent.

This is deliberately rule-based first, with an optional LLM polish pass
when `use_llm=True`. Rule-based generation is deterministic, fast, and
matches the "voice-first" latency budget — LLM polish is reserved for
weekly digests where users will tolerate a couple-second delay.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from tools.llm_client import get_recommendation_llm

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- helpers --
def _pct(x: float) -> str:
    return f"{int(round(x * 100))} persen"


def _format_concept_list(items: list[dict], key: str = "concept_name", n: int = 3) -> str:
    if not items:
        return "belum ada"
    names = [i.get(key, "—") for i in items[:n]]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", dan {names[-1]}"


# ------------------------------------------------- student-facing summary --
def generate_student_spoken_summary(analytics: dict) -> str:
    """Produces the audio-friendly Bahasa Indonesia summary."""
    if analytics.get("error"):
        return "Maaf, data analitik belum tersedia."

    name = analytics.get("student_name", "kamu").split()[0]
    n_sessions = analytics.get("n_sessions", 0)
    accuracy = analytics.get("quiz_accuracy", 0.0)
    overall = analytics.get("overall_mastery", 0.0)
    weak = analytics.get("weak_concepts", [])
    strong = analytics.get("strong_concepts", [])

    parts: list[str] = []
    parts.append(f"Halo {name}.")

    if n_sessions == 0:
        parts.append("Minggu ini kamu belum belajar sama sekali. Mari mulai sekarang!")
        return " ".join(parts)

    parts.append(
        f"Minggu ini kamu sudah belajar {n_sessions} sesi "
        f"dengan tingkat penguasaan rata-rata {_pct(overall)}."
    )

    if accuracy >= 0.8:
        parts.append(f"Akurasi kuis kamu sangat baik di {_pct(accuracy)}. Pertahankan!")
    elif accuracy >= 0.6:
        parts.append(f"Akurasi kuis kamu {_pct(accuracy)}. Teruskan latihan.")
    elif accuracy > 0:
        parts.append(
            f"Akurasi kuis kamu masih {_pct(accuracy)}. "
            "Jangan khawatir, kita akan kerjakan bersama."
        )

    if strong:
        parts.append(f"Kamu sudah kuat di {_format_concept_list(strong)}.")
    if weak:
        parts.append(
            f"Yang masih perlu kita perdalam: {_format_concept_list(weak)}."
        )

    return " ".join(parts)


# ----------------------------------------------- teacher-facing summary --
def generate_teacher_summary(analytics: dict) -> dict:
    """Produces a structured summary plus 1-3 alert lines."""
    if analytics.get("error"):
        return {"alerts": [], "headline": "Data tidak tersedia."}

    alerts: list[dict] = []
    student_name = analytics.get("student_name") or "Siswa"

    accuracy = analytics.get("quiz_accuracy", 0.0)
    n_attempts = analytics.get("n_quiz_attempts", 0)
    engagement = analytics.get("engagement_index", 0.0)
    miscons = analytics.get("open_misconceptions", [])

    if n_attempts >= 3 and accuracy < 0.5:
        alerts.append({
            "level": "warning",
            "title": f"{student_name}: akurasi rendah",
            "detail": (
                f"Akurasi {int(accuracy*100)}% dari {n_attempts} kuis. "
                "Disarankan sesi 1:1 atau remediasi terarah."
            ),
        })

    if engagement < 0.2 and analytics.get("n_sessions", 0) <= 1:
        alerts.append({
            "level": "warning",
            "title": f"{student_name}: keterlibatan rendah",
            "detail": "Kurang dari satu sesi per minggu. Periksa motivasi siswa.",
        })

    if miscons:
        alerts.append({
            "level": "info",
            "title": f"{student_name}: {len(miscons)} miskonsepsi terdeteksi",
            "detail": "; ".join(m["description"] for m in miscons[:3]),
        })

    if not alerts and analytics.get("overall_mastery", 0) >= 0.85:
        alerts.append({
            "level": "success",
            "title": f"{student_name}: penguasaan kuat",
            "detail": "Pertimbangkan materi tantangan tingkat lanjut.",
        })

    headline = (
        f"{student_name} — penguasaan {int(analytics.get('overall_mastery', 0)*100)}%, "
        f"akurasi kuis {int(accuracy*100)}%, "
        f"{analytics.get('n_sessions', 0)} sesi minggu ini."
    )
    return {"headline": headline, "alerts": alerts}


# ------------------------------------------------ classroom-level alerts --
def generate_classroom_alerts(classroom_summary: dict) -> list[dict]:
    if classroom_summary.get("error"):
        return []
    alerts: list[dict] = []
    weak = classroom_summary.get("class_weak_concepts", [])
    if weak and weak[0]["avg_mastery"] < 0.5:
        alerts.append({
            "level": "warning",
            "title": f"Konsep kelas lemah: {weak[0]['concept_name']}",
            "detail": (
                f"Rata-rata penguasaan kelas hanya "
                f"{int(weak[0]['avg_mastery']*100)}% pada {weak[0]['n_students']} siswa. "
                "Pertimbangkan re-teach materi ini."
            ),
        })
    if classroom_summary.get("avg_engagement_index", 0) < 0.3:
        alerts.append({
            "level": "info",
            "title": "Keterlibatan kelas rendah",
            "detail": "Rata-rata sesi per siswa di bawah ambang sehat.",
        })
    return alerts


# ----------------------------------------------------------- LLM polish --
async def generate_insights(
    analytics: dict,
    *,
    audience: str = "student",
    use_llm: bool = False,
    language: str = "id",
) -> dict:
    """
    audience: 'student' | 'teacher'
    Returns: {"spoken": str, "structured": dict}
    """
    if audience == "teacher":
        structured = generate_teacher_summary(analytics)
        spoken = structured["headline"]
    else:
        structured = {"summary": generate_student_spoken_summary(analytics)}
        spoken = structured["summary"]

    if not use_llm:
        return {"spoken": spoken, "structured": structured}

    # Optional LLM polish for weekly digests.
    try:
        llm = get_recommendation_llm(temperature=0.3)
        sys = (
            "Anda adalah pendidik yang ramah. Polish ringkasan berikut agar "
            "lebih hangat dan memotivasi. Jangan tambahkan informasi baru. "
            "Maksimum 3 kalimat. JANGAN gunakan markdown."
            if language == "id"
            else
            "You are a warm educator. Polish the following summary to be more "
            "encouraging. Add no new information. Maximum 3 sentences. No markdown."
        )
        resp = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=spoken)])
        polished = resp.content if hasattr(resp, "content") else str(resp)
        return {"spoken": polished.strip(), "structured": structured}
    except Exception as exc:  # pragma: no cover
        logger.warning("LLM polish failed, returning rule-based: %s", exc)
        return {"spoken": spoken, "structured": structured}
