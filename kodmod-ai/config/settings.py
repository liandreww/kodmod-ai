"""
KODMOD AI — Configuration Settings
==================================

Centralized settings using pydantic-settings. **This module is the only place
in the codebase allowed to read the environment.** Everything else imports
`settings`; `tests/static/test_no_stray_getenv.py` enforces that.

Environment variables can be supplied via:
- A `.env` file in the project root
- Real environment variables (preferred for production / Kubernetes)
- Docker secrets mounted as files

The naming convention mirrors the env keys (UPPER_SNAKE_CASE) so deployers
can grep the codebase to find every knob a single name corresponds to.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel for model ids that must be supplied by the deployer. Getters raise a
# readable error instead of letting a bogus id fail mid-conversation.
MODEL_UNSET = "SET_ME_IN_ENV"


class Settings(BaseSettings):
    """Application-wide settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Don't JSON-decode complex fields from env/.env. The only list field
        # (CORS_ALLOW_ORIGINS) accepts a plain comma-separated string via its
        # `mode="before"` validator; without this, `CORS_ALLOW_ORIGINS=*` in a
        # .env file raises a JSON parse error before the validator runs.
        enable_decoding=False,
    )

    # ------------------------------------------------------------------ env
    ENV: Literal["dev", "staging", "prod", "test"] = "dev"
    APP_NAME: str = "KODMOD AI"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = False

    # ------------------------------------------------------------------ api
    API_HOST: str = "0.0.0.0"  # noqa: S104  # bind-all is the container default; restrict via env in prod
    API_PORT: int = 8000
    CORS_ALLOW_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    JWT_SECRET: str = "change-me-in-production"  # noqa: S105  # placeholder; real value from env/secret
    JWT_ALG: str = "HS256"
    JWT_EXPIRE_MIN: int = 60 * 24  # 24h

    # ------------------------------------------------------------- database
    DB_USER: str = "kodmod"
    DB_PASSWORD: str = "kodmod"  # noqa: S105  # local dev default; real value from env/secret
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "kodmod"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    @property
    def DATABASE_URL(self) -> str:  # noqa: N802 (uppercase property is intentional)
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def LANGGRAPH_DB_URI(self) -> str:  # noqa: N802
        # AsyncPostgresSaver expects libpq-style DSN.
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # LangGraph checkpointing. "postgres" persists every turn; "memory" swaps
    # in the lock-free in-memory saver, which load tests need because
    # AsyncPostgresSaver serialises checkpoint writes on one process-wide lock.
    CHECKPOINTER: Literal["postgres", "memory"] = "postgres"

    # ---------------------------------------------------------------- redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    @property
    def REDIS_URL(self) -> str:  # noqa: N802
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ------------------------------------------------------------------- llm
    # OpenAI is the only provider. OPENAI_BASE_URL exists so the test stack can
    # point the same code at docker/llm_stub without a second code path.
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None

    # Per-role model identifiers. No defaults on purpose: the deployer picks.
    LLM_ROUTER_MODEL: str = MODEL_UNSET
    LLM_TUTOR_MODEL: str = MODEL_UNSET
    LLM_QUIZ_MODEL: str = MODEL_UNSET
    LLM_SCORING_MODEL: str = MODEL_UNSET
    LLM_RECOMMENDATION_MODEL: str = MODEL_UNSET
    LLM_REFLECTION_MODEL: str = MODEL_UNSET

    # ------------------------------------------------------------------- rag
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RAG_RERANK_ENABLED: bool = False
    RAG_TOP_K: int = 8
    RAG_RERANK_TOP_K: int = 4

    # ---------------------------------------------------------------- upload
    # Teacher-uploaded curriculum documents land here before ingestion.
    UPLOAD_DIR: Path = Path("./data/uploads")
    MAX_UPLOAD_MB: int = 25
    WS_MAX_FRAME_BYTES: int = 262_144  # per-frame inbound cap on /ws/chat

    # --------------------------------------------------------- observability
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_PROJECT: str = "kodmod-ai"
    LANGCHAIN_TRACING_V2: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_JSON: bool = True

    # ----------------------------------------------------------- pedagogy
    DEFAULT_DIFFICULTY: Literal["easy", "medium", "hard"] = "medium"
    DEFAULT_LANGUAGE: Literal["id", "en"] = "id"
    # Natural-language name (not a code) — appended verbatim to every agent's
    # system prompt via `tools.llm_client.language_instruction()` so LLM
    # output language stays consistent regardless of input language.
    GRAPH_LANGUAGE: str = "Bahasa Indonesia"
    QUIZ_PASS_THRESHOLD: float = 0.6
    QUIZ_MAX_ATTEMPTS_PER_QUESTION: int = 2
    MASTERY_PROMOTION: float = 0.8
    SOCRATIC_DEPTH: int = 3  # how many follow-up turns the tutor pursues

    # ----------------------------------------------------------- accessibility
    ACCESSIBILITY_DEFAULT_PROFILE: Literal["blind", "low_vision", "standard"] = "blind"
    MAX_SPOKEN_SENTENCE_WORDS: int = 22

    # ----------------------------------------------------------------- validators
    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("UPLOAD_DIR", mode="after")
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        try:
            v.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            # In tests / restricted CI we silently skip; the runtime user must
            # ensure this exists with proper perms in production.
            pass
        return v

    @property
    def MAX_UPLOAD_BYTES(self) -> int:  # noqa: N802
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor — call this everywhere instead of `Settings()`."""
    return Settings()


# Convenience singleton (most code does `from config.settings import settings`)
settings = get_settings()


# Side-effect: wire LangSmith env vars if enabled.
if settings.LANGCHAIN_TRACING_V2 and settings.LANGSMITH_API_KEY:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.LANGSMITH_PROJECT)
