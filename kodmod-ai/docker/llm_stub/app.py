"""Deterministic OpenAI-compatible stub for load / system tests.

NOT a mock of model quality — it returns canned, deterministic responses so that
Stage 7-9 can exercise the real HTTP/graph/DB/checkpointer path without cost,
network, or GPU. In-process pytest stages patch the LLM in Python instead
(see tests/_fakes/), and never hit this service.

Endpoints:
  GET  /health
  GET  /v1/models
  POST /v1/chat/completions      (streaming + non-streaming)
  POST /v1/embeddings           (1024-dim by default)
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

EMBED_DIM = int(os.getenv("KODMOD_STUB_EMBED_DIM", "1024"))

app = FastAPI(title="kodmod-llm-stub")


def _seeded_vector(text: str, dim: int) -> list[float]:
    """Deterministic unit-ish vector from a text hash."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    out: list[float] = []
    i = 0
    while len(out) < dim:
        b = h[i % len(h)]
        out.append(((b / 255.0) * 2.0) - 1.0)
        i += 1
        if i % len(h) == 0:
            h = hashlib.sha256(h).digest()
    norm = sum(v * v for v in out) ** 0.5 or 1.0
    return [v / norm for v in out]


def _looks_like_json_request(prompt: str) -> bool:
    p = prompt.lower()
    return "json" in p or "schema" in p or "rubric" in p or '"intent"' in p


def _canned_reply(prompt: str) -> str:
    """A safe, accessibility-friendly canned answer.

    If the caller clearly wants JSON (intent router / scoring rubric / analyzer),
    hand back a minimal valid object that downstream parsers accept.
    """
    if _looks_like_json_request(prompt):
        return json.dumps(
            {
                "intent": "tutoring",
                "confidence": 0.9,
                "score": 0.8,
                "is_correct": True,
                "feedback": "Jawaban kamu sudah tepat. Teruskan.",
                "misconceptions": [],
                "weak_concepts": [],
                "strong_concepts": [],
                "recommendations": ["Latihan lima soal lagi besok."],
                "reflection_score": 0.8,
            }
        )
    return (
        "Pecahan adalah bilangan yang menyatakan bagian dari keseluruhan. "
        "Pembilang berada di atas dan penyebut berada di bawah. "
        "Penyebut tidak boleh nol."
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "embed_dim": EMBED_DIM}


@app.get("/v1/models")
def models() -> dict:
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": "stub-chat", "object": "model", "created": now, "owned_by": "kodmod"},
            {
                "id": "text-embedding-3-small",
                "object": "model",
                "created": now,
                "owned_by": "kodmod",
            },
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    prompt = "\n".join(str(m.get("content", "")) for m in messages)
    reply = _canned_reply(prompt)
    model = body.get("model", "stub-chat")
    created = int(time.time())
    cid = "chatcmpl-stub-" + hashlib.sha1(prompt.encode()).hexdigest()[:12]

    if body.get("stream"):

        def _gen():
            for tok in reply.split(" "):
                chunk = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"content": tok + " "}, "finish_reason": None}
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            done = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream")

    prompt_tokens = max(1, len(prompt) // 4)
    completion_tokens = max(1, len(reply) // 4)
    return {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    body = await request.json()
    raw = body.get("input", "")
    inputs = raw if isinstance(raw, list) else [raw]
    dim = int(body.get("dimensions") or EMBED_DIM)
    data = [
        {"object": "embedding", "index": i, "embedding": _seeded_vector(str(t), dim)}
        for i, t in enumerate(inputs)
    ]
    total = sum(max(1, len(str(t)) // 4) for t in inputs)
    return {
        "object": "list",
        "data": data,
        "model": body.get("model", "text-embedding-3-small"),
        "usage": {"prompt_tokens": total, "total_tokens": total},
    }
