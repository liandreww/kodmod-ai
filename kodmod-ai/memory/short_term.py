"""
KODMOD AI — Short-Term Memory (Redis)
=====================================

Per-session ephemeral state: current tutoring turns, in-flight quiz state,
last spoken response (for "ulangi"/"repeat" commands), pacing preferences.

LangGraph already checkpoints the canonical state to Postgres. This Redis
layer is for *fast* reads needed inside a single turn — checkpoint reads
are too slow for sub-100ms voice-loop logic.

Keys are namespaced by session_id with a 24h TTL by default.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from config.settings import settings

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 60 * 60 * 24  # 24h
_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def _key(session_id: str, sub: str) -> str:
    return f"kodmod:session:{session_id}:{sub}"


async def set_value(session_id: str, sub: str, value: Any, ttl: int = _DEFAULT_TTL) -> None:
    r = await get_redis()
    await r.set(_key(session_id, sub), json.dumps(value, default=str), ex=ttl)


async def get_value(session_id: str, sub: str) -> Optional[Any]:
    r = await get_redis()
    v = await r.get(_key(session_id, sub))
    return json.loads(v) if v else None


async def delete_session(session_id: str) -> None:
    r = await get_redis()
    cursor = 0
    pattern = f"kodmod:session:{session_id}:*"
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=200)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break


# --- semantic helpers used by agents -------------------------------------
async def store_last_response(session_id: str, text: str, audio_url: Optional[str] = None) -> None:
    """Used by accessibility_agent so 'ulangi' can replay it."""
    await set_value(session_id, "last_response", {"text": text, "audio_url": audio_url})


async def fetch_last_response(session_id: str) -> Optional[dict]:
    return await get_value(session_id, "last_response")


async def append_tutoring_turn(session_id: str, turn: dict, max_turns: int = 12) -> None:
    """Push a turn into the rolling tutoring window."""
    r = await get_redis()
    key = _key(session_id, "tutoring_turns")
    pipe = r.pipeline()
    pipe.rpush(key, json.dumps(turn, default=str))
    pipe.ltrim(key, -max_turns, -1)
    pipe.expire(key, _DEFAULT_TTL)
    await pipe.execute()


async def fetch_tutoring_turns(session_id: str) -> list[dict]:
    r = await get_redis()
    items = await r.lrange(_key(session_id, "tutoring_turns"), 0, -1)
    return [json.loads(x) for x in items]


async def set_pacing(session_id: str, rate: float) -> None:
    await set_value(session_id, "tts_rate", rate)


async def get_pacing(session_id: str) -> float:
    v = await get_value(session_id, "tts_rate")
    return float(v) if v is not None else settings.TTS_RATE
