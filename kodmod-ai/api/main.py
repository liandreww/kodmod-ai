"""
KODMOD AI — FastAPI Application Entry
======================================

Mounts:
  /voice/*       — voice chat (REST + WebSocket)
  /quiz/*        — quiz session management
  /student/*     — student profile + dashboard
  /analytics/*   — student & teacher analytics
  /exercise/*    — exercise generation
  /content/*     — curriculum retrieval
  /health        — liveness + readiness
  /metrics       — Prometheus

Lifespan
--------
On startup: builds the LangGraph, opens DB pools, warms up models.
On shutdown: drains in-flight WebSockets and closes pools cleanly.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from api.routes import voice, quiz, student, analytics, exercise, content, health
from api.websockets import voice_stream
from config.logging import configure_logging
from config.settings import settings
from database.session import close_db, init_db
from graphs.main_graph import build_kodmod_graph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup / shutdown."""
    configure_logging()
    log.info("Starting KODMOD AI API")

    # 1. DB pools
    await init_db()

    # 2. LangGraph checkpointer + graph
    cp_cm = AsyncPostgresSaver.from_conn_string(settings.LANGGRAPH_DB_URI)
    app.state.checkpointer_cm = cp_cm
    checkpointer = await cp_cm.__aenter__()
    await checkpointer.setup()
    app.state.graph = await build_kodmod_graph(checkpointer=checkpointer)

    log.info("KODMOD AI ready (env=%s)", settings.ENV)
    yield

    # Shutdown
    log.info("Shutting down KODMOD AI")
    await app.state.checkpointer_cm.__aexit__(None, None, None)
    await close_db()


app = FastAPI(
    title="KODMOD AI",
    version="0.1.0",
    description="Voice-first agentic learning assistant for visually impaired students.",
    lifespan=lifespan,
)


# ---- Middleware -----------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Routers --------------------------------------------------------------

app.include_router(health.router)
app.include_router(voice.router, prefix="/voice", tags=["voice"])
app.include_router(quiz.router, prefix="/quiz", tags=["quiz"])
app.include_router(student.router, prefix="/student", tags=["student"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(exercise.router, prefix="/exercise", tags=["exercise"])
app.include_router(content.router, prefix="/content", tags=["content"])
app.include_router(voice_stream.router, prefix="/ws", tags=["websocket"])


# ---- Prometheus -----------------------------------------------------------

app.mount("/metrics", make_asgi_app())
