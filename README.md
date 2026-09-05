# KODMOD AI, an agentic learning assistant

> **LangGraph-based agentic tutor for visually impaired, blind, and low-vision learners.**

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

- **Accessibility first.** Every interaction can be completed by voice or by keyboard alone. No interface element is mandatory to *see*.
- **Agentic by design** — autonomous LangGraph agents collaborate, route, reflect, and self-correct rather than following fixed scripts.
- **Adaptive learning** — a persistent student model drives difficulty, pacing, remediation, and recommendations in real time.

The system serves three primary actors:

| Actor | Primary Interaction | Output |
|---|---|---|
| **Student** (visually impaired) | Voice or typed conversation | Explanations and quizzes, read aloud in the browser on request |
| **Teacher** | Web dashboard | Student progress, transcripts, subjects and curriculum uploads |
| **Admin** | Web dashboard | Accounts and invitation codes |

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
            │PostgreSQL │       │  pgvector  │      │    Redis     │
            │           │       │  (in PG)   │      │ (state/cache)│
            └───────────┘       └────────────┘      └──────────────┘
```

---

## 3. The Four Clusters

### Cluster 1, Practices & Tutoring
Intent Router → (Tutoring Agent | Mini-Quiz) → Accessibility.
Conversational, Socratic, RAG-grounded tutoring with conversational memory.

### Cluster 2, Quiz / Assessment
Problem Generator → Quiz Agent → student answer → Scoring Agent → Quiz Analyzer →
Student Model update. Adaptive difficulty driven by mastery scores.

### Cluster 3, Content & Exercise Management
Curriculum KB + RAG retrieval + Exercise Generator. Feeds both clusters above with audio-friendly, accessibility-compliant content.

### Cluster 4, Analytics & Reporting
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
│   ├── main_graph.py       # The one orchestrator; 13 nodes, no subgraphs
│   └── state.py            # KODMODState TypedDict
├── tools/                  # Tools bound to agents
│   ├── llm_client.py       # The only place a chat model is built
│   ├── rag_tool.py
│   ├── student_profile_tool.py
│   ├── quiz_generator_tool.py
│   ├── analytics_tool.py
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
│   ├── security.py         # Password hashing + token issuance
│   ├── dependencies.py     # current_user + the role gates
│   ├── chat_service.py     # Shared middle of a conversation turn
│   ├── routes/
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── quiz.py
│   │   ├── student.py
│   │   ├── teacher.py
│   │   ├── admin.py
│   │   ├── subjects.py     # Subjects, concepts, document uploads
│   │   ├── analytics.py
│   │   ├── exercise.py
│   │   └── content.py
│   └── websockets/
│       └── chat_stream.py
├── database/               # SQLAlchemy + Alembic
│   ├── models.py           # The whole schema; there is no schema.sql
│   └── migrations/
├── models/                 # Pydantic domain models
│   ├── user.py
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
├── config/
│   ├── settings.py
│   └── logging.py
├── tests/
├── scripts/
│   ├── create_admin.py     # The first admin; registration needs a code
│   ├── seed_curriculum.py
│   └── ingest_documents.py
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose.prod.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── ACCESSIBILITY.md
│   └── DEPLOYMENT.md
└── ...

frontend-dev/               # Next.js frontend, sibling of kodmod-ai/
├── src/app/                # Routes: /masuk /daftar /belajar /guru /admin
│   └── api/                # transcribe + speak, proxying OpenAI server-side
├── src/components/
└── src/lib/
└── scripts/
    ├── seed_curriculum.py
    └── ingest_documents.py
```

---

## 6. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** + LangChain | Stateful multi-agent graphs with persistence |
| LLM | **OpenAI**, per-role model ids from `.env` | One provider, one code path, no dead branches |
| Speech in and out | **OpenAI**, called from the browser via Next.js route handlers | Keeps audio off the API boundary; the key stays server-side |
| Embeddings | **text-embedding-3-small**, 1536-dim | Handles Indonesian and English, no local GPU |
| Reranker | **bge-reranker-v2-m3** (local, CPU) | Free, and degrades gracefully if it fails to load |
| Vector DB | **pgvector** | Co-located with relational data |
| Relational DB | PostgreSQL 16 | ACID + pgvector + JSONB |
| Cache / State | Redis 7 | Session state and the in-flight quiz cursor |
| API | FastAPI + Uvicorn | Async, WebSocket-first |
| Frontend | Next.js 16 (App Router) + Tailwind v4 | See `frontend-dev/` |
| Observability | LangSmith + Prometheus | End-to-end tracing |
| Deploy | Docker Compose | See `docker/` |

---

## 7. Quick Start

### Backend

```bash
cd kodmod-ai
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # fill in OPENAI_API_KEY and every LLM_*_MODEL

make up                       # Postgres + Redis
make migrate                  # create the schema (nothing is auto-loaded)
make seed                     # sample curriculum
make admin                    # the first admin account, prompts for a password

make dev                      # http://localhost:8000
```

The app refuses to start a turn while any `LLM_*_MODEL` is still `SET_ME_IN_ENV`,
so a missing model id fails immediately with a readable message instead of
halfway through a conversation.

### Frontend

```bash
cd frontend-dev
npm install
cp .env.example .env.local    # fill in OPENAI_API_KEY
npm run dev                   # http://localhost:3000
```

Sign in as the admin, mint an invitation code, and register a student or teacher
with it.

---

## 8. Deployment & Scaling

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for full Kubernetes manifests, GPU node-pool sizing, autoscaling rules, and cost optimization strategies.

---

## License & Compliance

KODMOD AI is built to comply with WCAG 2.2 AAA, FERPA (US student-data privacy), GDPR Article 9 (special-category data for minors), and ISO/IEC 40500 accessibility standards.
