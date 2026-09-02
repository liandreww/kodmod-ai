"""Stage 3 §3 — memory/short_term.py against real Redis.

Spec: docs/testplan/03-integration.md §3 (KM-INT-040..045).
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.redis,
    # Async fixtures run on the session loop (pyproject:
    # asyncio_default_fixture_loop_scope=session); the cached redis pool is
    # bound to that loop, so the test bodies must share it too.
    pytest.mark.asyncio(loop_scope="session"),
]

SID = "sess-int-short"


# --------------------------------------------------------------------------- #
# KM-INT-040 — set_value / get_value round-trip + TTL ~24h + key shape
# --------------------------------------------------------------------------- #
async def test_km_int_040_set_get_value_and_ttl(redis_client) -> None:  # type: ignore[no-untyped-def]
    from memory.short_term import _key, get_value, set_value

    await set_value(SID, "topic", {"concept": "pecahan"})
    assert await get_value(SID, "topic") == {"concept": "pecahan"}

    ttl = await redis_client.ttl(_key(SID, "topic"))
    assert 60 * 60 * 23 <= ttl <= 60 * 60 * 24


# --------------------------------------------------------------------------- #
# KM-INT-041 — delete_session removes every sub-key (SCAN + DEL)
# --------------------------------------------------------------------------- #
async def test_km_int_041_delete_session(redis_client) -> None:  # type: ignore[no-untyped-def]
    from memory.short_term import delete_session, get_value, set_value

    for sub in ("a", "b", "c"):
        await set_value(SID, sub, sub)
    await delete_session(SID)
    for sub in ("a", "b", "c"):
        assert await get_value(SID, sub) is None


# --------------------------------------------------------------------------- #
# KM-INT-042 — store_last_response / fetch_last_response
# --------------------------------------------------------------------------- #
async def test_km_int_042_last_response(redis_client) -> None:  # type: ignore[no-untyped-def]
    from memory.short_term import fetch_last_response, store_last_response

    await store_last_response(SID, "Pecahan adalah bagian dari keseluruhan.", audio_url=None)
    got = await fetch_last_response(SID)
    assert got == {"text": "Pecahan adalah bagian dari keseluruhan.", "audio_url": None}


# --------------------------------------------------------------------------- #
# KM-INT-043 — append_tutoring_turn keeps only the last 12 + sets EXPIRE
# --------------------------------------------------------------------------- #
async def test_km_int_043_tutoring_window_ltrim(redis_client) -> None:  # type: ignore[no-untyped-def]
    from memory.short_term import _key, append_tutoring_turn, fetch_tutoring_turns

    for i in range(15):
        await append_tutoring_turn(SID, {"role": "student", "text": f"turn {i}"})

    turns = await fetch_tutoring_turns(SID)
    assert len(turns) == 12
    assert turns[0]["text"] == "turn 3"
    assert turns[-1]["text"] == "turn 14"
    assert await redis_client.ttl(_key(SID, "tutoring_turns")) > 0


# --------------------------------------------------------------------------- #
# KM-INT-044 — get_pacing falls back to settings.TTS_RATE
# --------------------------------------------------------------------------- #
async def test_km_int_044_pacing_fallback_and_set(redis_client) -> None:  # type: ignore[no-untyped-def]
    from config.settings import settings
    from memory.short_term import get_pacing, set_pacing

    assert await get_pacing(SID) == pytest.approx(settings.TTS_RATE)
    await set_pacing(SID, 0.85)
    assert await get_pacing(SID) == pytest.approx(0.85)


# --------------------------------------------------------------------------- #
# KM-INT-045 — get_redis reuses one pool; close_redis clears it
# --------------------------------------------------------------------------- #
async def test_km_int_045_pool_reuse(redis_client) -> None:  # type: ignore[no-untyped-def]
    from memory import short_term as st

    a = await st.get_redis()
    b = await st.get_redis()
    assert a is b
    try:
        await st.close_redis()
    except RuntimeError:  # Windows ProactorEventLoop aclose() cross-loop quirk
        st._pool = None
    assert st._pool is None
    c = await st.get_redis()
    assert c is not a
