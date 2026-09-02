"""KM-UNIT-070..073 — central state factory (graphs/state.py).

Oracle: `initial_state` + the KODMODState TypedDict.
Spec: docs/testplan/01-unit.md §6.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from graphs.state import KODMODState, initial_state

pytestmark = pytest.mark.unit


def test_initial_state_fills_every_field() -> None:  # KM-UNIT-070
    st = initial_state("s1", str(uuid4()))
    missing = set(KODMODState.__annotations__) - set(st)
    assert not missing, f"initial_state left fields unset: {sorted(missing)}"
    assert st["intent"] == "unknown"
    assert st["next_action"] == "route_intent"
    assert st["current_difficulty"] == "medium"
    assert st["detected_language"] == "id"
    assert st["emotional_state"] == "neutral"
    assert st["last_node"] == "entry"


def test_session_id_is_required_positional() -> None:  # KM-UNIT-071
    with pytest.raises(TypeError):
        initial_state(student_id=str(uuid4()))  # type: ignore[call-arg]


def test_ids_unique_and_started_at_is_iso() -> None:  # KM-UNIT-072
    a = initial_state("s1", str(uuid4()))
    b = initial_state("s1", str(uuid4()))
    assert a["request_id"] != b["request_id"]
    assert a["trace_id"] != b["trace_id"]
    # parseable ISO-8601 (UTC, tz-aware)
    parsed = datetime.fromisoformat(a["started_at"])
    assert parsed.tzinfo is not None


def test_messages_starts_as_empty_list() -> None:  # KM-UNIT-073
    st = initial_state("s1", str(uuid4()))
    assert st["messages"] == []
    assert isinstance(st["messages"], list)
