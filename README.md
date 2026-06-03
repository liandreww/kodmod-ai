# KODMOD AI — Voice-First Agentic Learning Assistant

> **Multimodal LangGraph-based AI ecosystem for visually impaired, blind, and low-vision learners.**

KODMOD AI is a production-grade agentic learning assistant built around four collaborating clusters that together deliver conversational tutoring, adaptive spoken assessment, personalized content generation, and rich learning analytics — all through an audio-first interface.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture at a Glance](#2-architecture-at-a-glance)
3. [The Four Clusters](#3-the-four-clusters)
4. [LangGraph Workflow](#4-langgraph-workflow)
5. [Folder Structure](#5-folder-structure)
6. [Tech Stack](#6-tech-stack)
7. [Quick Start](#7-quick-start)
8. [Deployment & Scaling](#8-deployment--scaling)

---

## 1. System Overview

KODMOD AI is designed around three non-negotiable principles:

- **Accessibility first** — every interaction can be completed with voice alone. No interface element is mandatory to *see*.
- **Agentic by design** — autonomous LangGraph agents collaborate, route, reflect, and self-correct rather than following fixed scripts.
- **Adaptive learning** — a persistent student model drives difficulty, pacing, remediation, and recommendations in real time.

The system serves three primary actors:

| Actor | Primary Interaction | Output |
|---|---|---|
| **Student** (visually impaired) | Voice conversation, spoken quizzes | Spoken explanations, audio feedback, personalized exercises |
| **Teacher** | Web dashboard + voice queries | Class analytics, intervention recommendations, content authoring |
| **Admin** | Configuration & monitoring | System health, content moderation, privacy controls |

---

## 2. Architecture at a Glance

```
                         ┌──────────────────────────────────┐
                         │      Voice / Audio Frontend      │
                         │  (Web + Mobile, WCAG 2.2 AAA)    │
                         └───────────────┬──────────────────┘
                                         │ WebSocket (PCM/Opus)
                         ┌───────────────▼──────────────────┐
                         │       FastAPI Gateway            │
                         │  (Auth, Rate Limit, Streaming)   │
                         └───────────────┬──────────────────┘
                                         │
                         ┌───────────────▼──────────────────┐
                         │     LangGraph Orchestrator       │
                         │   (Stateful Multi-Agent Graph)   │
                         └───┬───────┬────────┬────────┬────┘
                             │       │        │        │
        ┌────────────────────▼─┐  ┌──▼──────┐ ┌▼──────┐ ┌▼─────────────┐
        │ Cluster: Practices & │  │Cluster: │ │Cluster│ │ Cluster:     │
        │     Tutoring         │  │ Quiz /  │ │Content│ │ Analytics &  │
        │                      │  │Assessmnt│ │& Exer.│ │  Reporting   │
        └──────────┬───────────┘  └────┬────┘ └───┬───┘ └──────┬───────┘
                   │                   │          │            │
                   └───────────────────┴──────────┴────────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
            ┌─────▼─────┐       ┌──────▼─────┐      ┌───────▼──────┐
            │PostgreSQL │       │ pgvector / │      │    Redis     │
            │+ pgvector │       │  Qdrant    │      │ (state/cache)│
            └───────────┘       └────────────┘      └──────────────┘
```

---

## 3. The Four Clusters

### 🟦 Cluster 1 — Practices & Tutoring
Voice-in → STT → Intent Router → (Tutoring Agent | Mini-Quiz) → TTS → Voice-out.
Conversational, Socratic, RAG-grounded tutoring with conversational memory.

### 🟨 Cluster 2 — Quiz / Assessment
Problem Generator → Quiz Agent → spoken delivery → student answer → STT → Scoring Agent → Quiz Analyzer → Student Model update.
Adaptive difficulty driven by mastery scores.

### 🟧 Cluster 3 — Content & Exercise Management
Curriculum KB + RAG retrieval + Exercise Generator. Feeds both clusters above with audio-friendly, accessibility-compliant content.

### 🟩 Cluster 4 — Analytics & Reporting
Learning Analytics Agent aggregates every interaction and powers the Student Dashboard, Teacher Dashboard, and Recommendation Agent.

> See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full per-cluster breakdown and data flow diagrams.

---

## 4. LangGraph Workflow

The orchestrator is a single `StateGraph` whose nodes are agents and whose edges are conditional routes driven by the Intent Router. State is persisted via `AsyncPostgresSaver` so sessions survive restarts and support human-in-the-loop interrupts.

See [`graphs/main_graph.py`](graphs/main_graph.py) for the full implementation.

---

## 5. Folder Structure

```
kodmod-ai/
├── agents/                 # LangGraph node agents (one file per agent)
│   ├── intent_router.py
│   ├── tutoring_agent.py
│   ├── quiz_agent.py
│   ├── scoring_agent.py
│   ├── quiz_analyzer.py
│   ├── analytics_agent.py
│   ├── recommendation_agent.py
│   ├── accessibility_agent.py
│   ├── problem_generator.py
│   └── reflection_agent.py
├── graphs/                 # LangGraph graph definitions
│   ├── main_graph.py       # Top-level orchestrator
│   ├── tutoring_subgraph.py
│   ├── quiz_subgraph.py
│   └── state.py            # KODMODState TypedDict
├── tools/                  # Tools bound to agents
│   ├── rag_tool.py
│   ├── student_profile_tool.py
│   ├── quiz_generator_tool.py
│   ├── analytics_tool.py
│   ├── voice_tool.py
│   └── database_tool.py
├── memory/                 # Memory subsystems
│   ├── short_term.py       # Redis-backed session memory
│   ├── long_term.py        # Postgres mastery graph
│   └── episodic.py         # Notable-event log
├── rag/                    # Retrieval pipeline
│   ├── ingestion.py
│   ├── chunking.py
│   ├── embeddings.py
│   ├── retriever.py
│   └── reranker.py
├── api/                    # FastAPI surface
│   ├── main.py
│   ├── routes/
│   │   ├── voice.py
│   │   ├── quiz.py
│   │   ├── student.py
│   │   ├── analytics.py
│   │   ├── exercise.py
│   │   └── content.py
│   └── websockets/
│       └── voice_stream.py
├── database/               # SQLAlchemy + Alembic
│   ├── schema.sql
│   ├── models.py
│   └── migrations/
├── models/                 # Pydantic domain models
│   ├── student.py
│   ├── session.py
│   ├── quiz.py
│   └── content.py
├── analytics/              # Analytics engine
│   ├── student_model.py    # Mastery graph + BKT
│   ├── aggregator.py
│   └── insights.py
├── accessibility/          # A11y helpers
│   ├── narration.py        # Visual → descriptive text
│   ├── simplifier.py
│   └── voice_commands.py
├── prompts/                # System prompts (versioned)
│   ├── tutoring.md
│   ├── scoring.md
│   ├── analyzer.md
│   └── ...
├── voice/                  # STT + TTS pipelines
│   ├── stt.py
│   ├── tts.py
│   └── streaming.py
├── config/
│   ├── settings.py
│   └── logging.py
├── tests/
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose.prod.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── ACCESSIBILITY.md
│   └── DEPLOYMENT.md
└── scripts/
    ├── seed_curriculum.py
    └── ingest_documents.py
```

---

## 6. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** + LangChain | Stateful multi-agent graphs with persistence |
| LLM | Claude / GPT-4.1 / Llama 3 70B (configurable) | Quality + on-prem fallback |
| STT | **Faster-Whisper** (on-device) + Deepgram (streaming) | Latency + cost balance |
| TTS | **Piper** (offline) + ElevenLabs (premium) | Accessibility-first, low latency |
| Embeddings | **BGE-M3** | Multilingual, top retrieval quality |
| Vector DB | **pgvector** (or Qdrant for scale) | Co-located with relational data |
| Relational DB | PostgreSQL 16 | ACID + pgvector + JSONB |
| Cache / State | Redis 7 | Session state, rate limits, pub/sub |
| API | FastAPI + Uvicorn | Async, WebSocket-first |
| Observability | LangSmith + Prometheus + Grafana + OpenTelemetry | End-to-end tracing |
| Deploy | Docker + Kubernetes (Helm) | Horizontal scale, GPU node pools |

---

## 7. Quick Start

```bash
# 1. Clone and install
git clone <repo> && cd kodmod-ai
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Start infrastructure
docker compose -f docker/docker-compose.yml up -d

# 3. Run migrations and seed
alembic upgrade head
python scripts/seed_curriculum.py

# 4. Start the API
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 5. Open the voice client
open http://localhost:8000/client
```

---

## 8. Deployment & Scaling

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for full Kubernetes manifests, GPU node-pool sizing, autoscaling rules, and cost optimization strategies.

---

## License & Compliance

KODMOD AI is built to comply with WCAG 2.2 AAA, FERPA (US student-data privacy), GDPR Article 9 (special-category data for minors), and ISO/IEC 40500 accessibility standards.
