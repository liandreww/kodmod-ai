"""
KODMOD AI — Student Self-Service Routes
=======================================

- GET /student/me/profile  -> the signed-in student's learning profile

Account fields (name, language, password) are edited through `/auth/me`.
This module is only about learning state.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.dependencies import require_student
from database.models import User
from memory.long_term import fetch_weak_concepts, load_profile
from models.user import UserOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["student"])


@router.get("/me/profile")
async def my_profile(student: User = Depends(require_student)) -> dict:
    """Account details plus mastery, weak concepts, and the practice streak."""
    profile = await load_profile(student.id)
    mastery = profile.get("mastery", {})
    weak = await fetch_weak_concepts(student.id, n=5)

    return {
        "account": UserOut.model_validate(student).model_dump(mode="json"),
        "overall_mastery": (sum(mastery.values()) / len(mastery)) if mastery else 0.0,
        "mastery": mastery,
        "weak_concepts": weak,
        "streak_days": profile.get("streak_days", 0),
    }
