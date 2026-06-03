"""
KODMOD AI — Logging Configuration
=================================

Structured JSON logs in production, human-readable colored logs in dev.
All logs flow through the standard `logging` module so third-party libs
(LangChain, FastAPI, SQLAlchemy) inherit the same formatting.

Each log record carries:
- timestamp (ISO 8601 UTC)
- level
- logger name
- message
- session_id / student_id when set via contextvars
- exception info when present
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from typing import Any, Dict, Optional

from config.settings import settings

# Per-request context that any logger can read without explicit passing.
_session_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "kodmod_session", default=None
)
_student_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "kodmod_student", default=None
)


def set_log_context(session_id: Optional[str] = None, student_id: Optional[str] = None) -> None:
    if session_id is not None:
        _session_var.set(session_id)
    if student_id is not None:
        _student_var.set(student_id)


def clear_log_context() -> None:
    _session_var.set(None)
    _student_var.set(None)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if (sid := _session_var.get()):
            payload["session_id"] = sid
        if (uid := _student_var.get()):
            payload["student_id"] = uid

        # Include any user-attached extras.
        std_keys = set(logging.LogRecord(
            "n", 0, "p", 0, "m", None, None, None
        ).__dict__.keys()) | {"message", "asctime"}
        for k, v in record.__dict__.items():
            if k not in std_keys and not k.startswith("_"):
                try:
                    json.dumps(v)
                    payload[k] = v
                except (TypeError, ValueError):
                    payload[k] = repr(v)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _PrettyFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ctx = ""
        if (sid := _session_var.get()):
            ctx += f" [s={sid[:8]}]"
        if (uid := _student_var.get()):
            ctx += f" [u={uid[:8]}]"
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        return (
            f"{color}{ts} {record.levelname:<8}{self.RESET} "
            f"{record.name}{ctx}: {record.getMessage()}"
        )


def configure_logging(level: Optional[str] = None) -> None:
    """Idempotent — safe to call from main, tests, or Celery workers."""
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_JSON and settings.ENV != "dev":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_PrettyFormatter())

    root.addHandler(handler)
    root.setLevel(level or settings.LOG_LEVEL)

    # Tame noisy libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
