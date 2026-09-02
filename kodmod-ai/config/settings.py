"""
KODMOD AI — Configuration Settings
==================================

Centralized settings using pydantic-settings. All environment-driven knobs
flow through here so the rest of the codebase imports `settings` and never
touches `os.environ` directly.

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
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ------------------------------------------------------------------ api
    API_HOST: str = "0.0.0.0"  # noqa: S104  # bind-all is the container default; restrict via env in prod
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"
    CORS_ALLOW_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
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
    KODMOD_LLM_PROVIDER: Literal["anthropic", "openai", "ollama", "vllm"] = "anthropic"
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    VLLM_BASE_URL: str = "http://localhost:8001/v1"

    # Per-role model identifiers (overridable per provider via env).
    LLM_ROUTER_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_TUTOR_MODEL: str = "claude-opus-4-7"
    LLM_QUIZ_MODEL: str = "claude-sonnet-4-6"
    LLM_SCORING_MODEL: str = "claude-sonnet-4-6"
    LLM_RECOMMENDATION_MODEL: str = "claude-sonnet-4-6"
    LLM_REFLECTION_MODEL: str = "claude-haiku-4-5-20251001"

    # ------------------------------------------------------------------- rag
    EMBEDDING_PROVIDER: Literal["bge-m3", "openai", "sentence-transformers"] = "bge-m3"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    VECTOR_BACKEND: Literal["pgvector", "qdrant"] = "pgvector"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RAG_TOP_K: int = 8
    RAG_RERANK_TOP_K: int = 4

    # ----------------------------------------------------------------- voice
    STT_BACKEND: Literal["faster-whisper", "openai-whisper", "deepgram"] = "faster-whisper"
    STT_MODEL: str = "large-v3"
    STT_DEVICE: Literal["cuda", "cpu", "auto"] = "auto"
    STT_COMPUTE_TYPE: str = "float16"
    STT_LANGUAGE: str = "id"  # Bahasa Indonesia primary
    DEEPGRAM_API_KEY: str | None = None

    TTS_BACKEND: Literal["piper", "azure", "elevenlabs", "coqui"] = "piper"
    TTS_VOICE: str = "id-ID-ArdiNeural"
    TTS_RATE: float = 1.0
    AZURE_TTS_KEY: str | None = None
    AZURE_TTS_REGION: str | None = None
    ELEVENLABS_API_KEY: str | None = None

    # Voice on/off switches — when false the stt/tts graph nodes become
    # pass-throughs so the whole turn is text in / text out (cheaper testing).
    TTS_ENABLED: bool = True
    STT_ENABLED: bool = True

    AUDIO_DIR: Path = Path("/var/lib/kodmod/audio")
    UPLOAD_DIR: Path = Path("/var/lib/kodmod/uploads")
    MAX_AUDIO_SECONDS: int = 120

    # --------------------------------------------------------- observability
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_PROJECT: str = "kodmod-ai"
    LANGCHAIN_TRACING_V2: bool = False
    PROMETHEUS_ENABLED: bool = True
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_JSON: bool = True

    # ----------------------------------------------------------- pedagogy
    DEFAULT_DIFFICULTY: Literal["easy", "medium", "hard"] = "medium"
    DEFAULT_LANGUAGE: Literal["id", "en"] = "id"
    QUIZ_PASS_THRESHOLD: float = 0.6
    MASTERY_PROMOTION: float = 0.8
    SOCRATIC_DEPTH: int = 3  # how many follow-up turns the tutor pursues

    # ----------------------------------------------------------- accessibility
    ACCESSIBILITY_DEFAULT_PROFILE: Literal["blind", "low_vision", "standard"] = "blind"
    SSML_ENABLED: bool = True
    MAX_SPOKEN_SENTENCE_WORDS: int = 22

    # ----------------------------------------------------------------- validators
    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("AUDIO_DIR", "UPLOAD_DIR", mode="after")
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        try:
            v.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            # In tests / restricted CI we silently skip; the runtime user must
            # ensure these exist with proper perms in production.
            pass
        return v


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
