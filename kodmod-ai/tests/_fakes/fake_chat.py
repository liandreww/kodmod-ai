"""Deterministic fake chat model for stubbing the per-agent LLM getters.

``make_fake_chat(role)`` returns a LangChain chat model that:
  * responds deterministically (no network),
  * emits a role-appropriate payload — JSON for parsers (intent_router, scoring,
    quiz_analyzer, reflection), prose for tutor / recommendation,
  * supports ``.with_structured_output(Model)`` by returning a filled example.

If an agent's real prompt shape drifts, adjust ``_ROLE_PAYLOADS`` here — this is
the single choke point for "what the fake says".
"""

from __future__ import annotations

import json
from typing import Any

try:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
except Exception:  # pragma: no cover - langchain not importable during scaffold
    GenericFakeChatModel = object  # type: ignore[assignment,misc]
    AIMessage = object  # type: ignore[assignment,misc]


_PROSE = (
    "Pecahan adalah bilangan yang menyatakan bagian dari keseluruhan. "
    "Pembilang ada di atas dan penyebut ada di bawah. Penyebut tidak boleh nol."
)

_ROLE_PAYLOADS: dict[str, str] = {
    "router": json.dumps({"intent": "tutoring", "confidence": 0.92}),
    "tutor": _PROSE,
    "quiz": json.dumps(
        {
            "questions": [
                {
                    "question_id": "q1",
                    "text": "Berapa hasil satu per dua ditambah satu per dua?",
                    "type": "mcq",
                    "options": ["A. satu", "B. dua", "C. nol", "D. tiga"],
                    "expected_answer": "A",
                    "concept_id": "pecahan",
                    "difficulty": "easy",
                }
            ]
        }
    ),
    "scoring": json.dumps(
        {"score": 0.85, "is_correct": True, "feedback": "Jawabanmu tepat. Bagus."}
    ),
    "recommendation": json.dumps(
        {
            "recommendations": [
                {
                    "type": "practice",
                    "text": "Kerjakan lima soal pecahan lagi besok pagi.",
                    "concept_id": "pecahan",
                }
            ],
            "spoken_intro": "Inilah rekomendasi untukmu.",
        }
    ),
    "reflection": json.dumps(
        {
            "pedagogy": 0.8,
            "accessibility": 0.9,
            "groundedness": 0.8,
            "safety": 1.0,
            "overall_score": 0.8,
            "needs_rewrite": False,
            "issues": [],
            "rewritten": "",
        }
    ),
}


def role_payload(role: str) -> str:
    return _ROLE_PAYLOADS.get(role, _PROSE)


class _StructuredWrapper:
    """Minimal shim so ``.with_structured_output(Model)`` works in tests."""

    def __init__(self, model: Any) -> None:
        self._model = model

    async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
        return _example_instance(self._model)

    def invoke(self, *_a: Any, **_k: Any) -> Any:
        return _example_instance(self._model)


def _example_instance(model: Any) -> Any:
    """Build a best-effort instance of a pydantic model with dummy field values."""
    try:
        fields = model.model_fields  # pydantic v2
    except AttributeError:  # pragma: no cover
        return model()
    kwargs: dict[str, Any] = {}
    for name, field in fields.items():
        ann = getattr(field, "annotation", str)
        if ann in (int, float):
            kwargs[name] = 0
        elif ann is bool:
            kwargs[name] = True
        elif ann is list or getattr(ann, "__origin__", None) is list:
            kwargs[name] = []
        elif ann is dict or getattr(ann, "__origin__", None) is dict:
            kwargs[name] = {}
        else:
            kwargs[name] = "tutoring" if name == "intent" else "x"
    try:
        return model(**kwargs)
    except Exception:  # pragma: no cover
        return model.model_construct(**kwargs)


def make_fake_chat(role: str) -> Any:
    """Return a fake chat model that always answers with ``role_payload(role)``.

    Prefers a real ``GenericFakeChatModel`` fed an *infinite* message stream
    (``itertools.repeat``) so ``.ainvoke`` / ``.invoke`` never raise
    ``StopIteration``. Falls back to a hand-rolled stub if langchain isn't
    importable during scaffolding.
    """
    import itertools

    payload = role_payload(role)

    if GenericFakeChatModel is not object:
        try:
            model = GenericFakeChatModel(messages=itertools.repeat(AIMessage(content=payload)))
            # attach a structured-output shim without subclassing (pydantic model)
            object.__setattr__(model, "with_structured_output", _make_structured_shim())
            return model
        except Exception:  # pragma: no cover
            pass
    return _BareStub(payload)


def _make_structured_shim():  # type: ignore[no-untyped-def]
    def with_structured_output(schema: Any, **_kw: Any) -> Any:
        return _StructuredWrapper(schema)

    return with_structured_output


class _BareStub:
    """Fallback if GenericFakeChatModel is unavailable."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
        return AIMessage(content=self._payload)

    def invoke(self, *_a: Any, **_k: Any) -> Any:
        return AIMessage(content=self._payload)

    async def astream(self, *_a: Any, **_k: Any):
        for tok in self._payload.split(" "):
            yield AIMessage(content=tok + " ")

    def with_structured_output(self, schema: Any, **_kw: Any) -> Any:
        return _StructuredWrapper(schema)
