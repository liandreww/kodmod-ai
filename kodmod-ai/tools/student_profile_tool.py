"""
KODMOD AI — Student Profile Tool
================================

Exposes student state (profile, mastery, recent recommendations) to
agents that benefit from personalisation. Wraps `memory.long_term`
behind a LangChain-style tool interface so agents can call it via
function-calling or directly from Python.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from memory.long_term import (
    fetch_active_recommendations,
    fetch_open_misconceptions,
    fetch_weak_concepts,
    load_profile,
)

logger = logging.getLogger(__name__)


class StudentProfileInput(BaseModel):
    student_id: str = Field(..., description="UUID of the student")
    include_misconceptions: bool = True
    include_recommendations: bool = True


async def fetch_student_profile(
    student_id: str,
    *,
    include_misconceptions: bool = True,
    include_recommendations: bool = True,
) -> dict:
    """Return the structured profile bundle. Used both as a tool and directly."""
    sid = uuid.UUID(student_id)
    profile = await load_profile(sid)
    weak = await fetch_weak_concepts(sid, n=5)
    out: dict = {**profile, "weak_concepts": weak}
    if include_misconceptions:
        out["open_misconceptions"] = await fetch_open_misconceptions(sid)
    if include_recommendations:
        out["active_recommendations"] = await fetch_active_recommendations(sid, limit=5)
    return out


def get_student_profile_tool() -> StructuredTool:
    """Construct the LangChain tool wrapper."""
    return StructuredTool.from_function(
        coroutine=fetch_student_profile,
        name="get_student_profile",
        description=(
            "Retrieve a student's learning profile, mastery scores, weak concepts, "
            "open misconceptions, and active recommendations. Call this whenever you "
            "need to personalise tutoring or quiz generation."
        ),
        args_schema=StudentProfileInput,
    )
