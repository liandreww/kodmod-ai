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
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from prometheus_client import make_asgi_app
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from api.routes import analytics, content, exercise, health, quiz, student, voice
from api.websockets import voice_stream
from config.logging import configure_logging
from config.settings import settings
from database.session import close_db, init_db
from graphs.main_graph import build_kodmod_graph

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup / shutdown."""
    configure_logging()
    log.info("Starting KODMOD AI API")

    # 1. DB pools
    await init_db()

    # 2. LangGraph checkpointer + graph.
    # AsyncPostgresSaver serialises every checkpoint op on one process-wide
    # asyncio.Lock (langgraph internal), so under concurrency the graph turns
    # run strictly one at a time — fine for prod, fatal for the load probe
    # (KM-PERF-020). A load run sets KODMOD_CHECKPOINTER=memory to swap in the
    # lock-free in-memory saver; everything else keeps Postgres persistence.
    app.state.checkpointer_pool = None
    checkpointer: BaseCheckpointSaver
    if os.getenv("KODMOD_CHECKPOINTER", "postgres").lower() == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        log.info("Checkpointer: in-memory (KODMOD_CHECKPOINTER=memory)")
    else:
        cp_pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
            settings.LANGGRAPH_DB_URI,
            open=False,
            max_size=settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await cp_pool.open()
        app.state.checkpointer_pool = cp_pool
        checkpointer = AsyncPostgresSaver(cp_pool)
        await checkpointer.setup()
    app.state.graph = await build_kodmod_graph(checkpointer=checkpointer)

    log.info("KODMOD AI ready (env=%s)", settings.ENV)
    yield

    # Shutdown
    log.info("Shutting down KODMOD AI")
    if app.state.checkpointer_pool is not None:
        await app.state.checkpointer_pool.close()
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
