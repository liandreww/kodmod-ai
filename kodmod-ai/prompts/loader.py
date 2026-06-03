"""
KODMOD AI — Prompt Loader
=========================

Loads prompt templates from `prompts/*.md` so the system prompts that
agents use are visible, version-controlled, and reviewable separately
from code. Supports lightweight `{variable}` interpolation.

Usage:

    from prompts.loader import load_prompt
    template = load_prompt("tutoring_system")
    rendered = template.format(language="id", mastery_level=0.4)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def load_prompt(name: str, *, language: Optional[str] = None) -> str:
    """
    Load a prompt by name. If `language` is given, prefers `<name>.<language>.md`,
    falling back to `<name>.md`.

    Returns the raw template string. Caller is responsible for `.format()` calls.
    """
    candidates = []
    if language:
        candidates.append(_PROMPTS_DIR / f"{name}.{language}.md")
    candidates.append(_PROMPTS_DIR / f"{name}.md")

    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"Prompt {name!r} (lang={language!r}) not found. Looked in: "
        + ", ".join(str(c) for c in candidates)
    )


def render_prompt(name: str, *, language: Optional[str] = None, **kwargs) -> str:
    template = load_prompt(name, language=language)
    try:
        return template.format(**kwargs)
    except KeyError as exc:
        raise KeyError(
            f"Prompt {name!r} expected variable {exc.args[0]!r} which was not provided."
        ) from exc
