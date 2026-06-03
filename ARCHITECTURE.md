# KODMOD AI — Architecture

This document explains how the four clusters from the design diagrams
map onto the codebase.

## 1. High-Level View

```
                            ┌──────────────────────────────────┐
            student speech  │          Voice Layer             │
        ────────────────►   │   /ws/voice  (WebSocket)         │
                            │   StreamingSTT  +  stream_tts    │
                            └────────────┬─────────────────────┘
                                         │
                                         ▼
                            ┌──────────────────────────────────┐
                            │      LangGraph (StateGraph)      │
                            │                                  │
                            │  stt → intent_router ─┬─► tutoring
                            │                       ├─► quiz subgraph
                            │                       ├─► analytics
                            │                       └─► meta-cmd
                            │                                  │
                            │  every node persists via         │
                            │  AsyncPostgresSaver checkpointer │
                            └────────────┬─────────────────────┘
                                         │
                  ┌──────────────────────┼──────────────────────┐
                  ▼                      ▼                      ▼
             RAG (pgvector or       Postgres OLTP           Redis (short-
             qdrant + BGE-M3)       (curriculum,            term memory)
                                    mastery, attempts,
                                    interactions)
```

## 2. Cluster Mapping

### Cluster 1 — Practices & Tutoring  (`graphs/main_graph.py`)

The "What do you want?" diamond is `route_after_intent()`. The Yes/No
remediation diamond after scoring is `route_after_scoring()`:

| Diagram element              | Code                                                |
|------------------------------|-----------------------------------------------------|
| Speech in / STT              | `voice/stt.py::stt_node`                            |
| Question / Answering branch  | `agents/tutoring_agent.py::tutoring_node`           |
| Mini quiz branch             | `agents/quiz_agent.py::mini_quiz_node`              |
| Scoring Agent                | `agents/scoring_agent.py::scoring_node`             |
| Yes branch (mastery met)     | `analytics/student_model.py::update_student_model_node` |
| No branch (remediation)      | `agents/tutoring_agent.py::tutoring_node` (re-entry)|
| TTS out                      | `voice/tts.py::tts_node`                            |
| Materi ajar (RAG)            | `rag/retriever.py::rag_retrieval_node`              |

### Cluster 2 — Quiz / Assessment

| Diagram element              | Code                                                |
|------------------------------|-----------------------------------------------------|
| Soal Quiz (teacher-authored) | `database/models.py::Exercise`                      |
| Problem Generator            | `agents/problem_generator.py::problem_generator_node` |
| Quiz / Assessment ask        | `agents/quiz_agent.py::quiz_node`                   |
| Input → STT                  | `voice/stt.py` (re-entry on each answer)            |
| Scoring Agent                | `agents/scoring_agent.py::scoring_node`             |
| Quiz Analyzer (Hasil Analisis) | `agents/quiz_analyzer.py::quiz_analyzer_node`     |
| Store + Student Model        | `analytics/student_model.py`, `database/models.py`  |
| TTS out                      | `voice/tts.py::tts_node`                            |
| Bridge to Cluster 4          | analytics_node consumes the analyzer output         |

### Cluster 3 — Content & Exercise Management

| Diagram element              | Code                                                |
|------------------------------|-----------------------------------------------------|
| Cluster Analytics signal     | mastery scores read by `problem_generator_node`     |
| Problem Generator            | `agents/problem_generator.py`                       |
| DB                           | `database/models.py::Exercise`, `Concept`           |
| Store                        | `tools/database_tool.py`                            |

### Cluster 4 — Analytics & Reporting

| Diagram element              | Code                                                |
|------------------------------|-----------------------------------------------------|
| Learning Analytics Agent     | `agents/analytics_agent.py::analytics_node`         |
| Student Dashboard            | `api/routes/analytics.py::student_analytics`        |
| Teacher Dashboard            | `api/routes/analytics.py::classroom_analytics`      |
| Spoken summary               | `analytics/insights.py::generate_student_spoken_summary` |
| Recommendation feed          | `agents/recommendation_agent.py::recommendation_node` |

## 3. State Flow

`graphs/state.py::KODMODState` is the single TypedDict that travels
through the graph. The fields most agents read/write are:

- `transcribed_text`, `intent`, `intent_confidence`
- `current_topic`, `concept_id`, `difficulty`
- `tutoring_context: list[TutoringTurn]`
- `retrieved_docs: list[RetrievedDoc]`
- `quiz_session_id`, `quiz_questions`, `current_question_index`,
  `quiz_score`, `cumulative_quiz_score`, `misconceptions_detected`
- `mastery_scores: dict[concept_id, float]`
- `learning_profile: LearningProfile`
- `analytics_summary: AnalyticsSummary`
- `recommendations: list[Recommendation]`
- `accessible_response: str` (post-`accessibility_node`)
- `messages` (LangChain message list with `add_messages` reducer)

## 4. Persistence

| Layer              | Store                | What it holds                       |
|--------------------|----------------------|-------------------------------------|
| Graph checkpoints  | Postgres (langgraph) | One row per (thread_id, step)       |
| Curriculum + RAG   | Postgres + pgvector  | concepts, lessons, curriculum_chunks|
| OLTP / analytics   | Postgres             | sessions, attempts, mastery, reports|
| Short-term memory  | Redis                | last response, pacing, session vars |
| Vector alt         | Qdrant (optional)    | when VECTOR_BACKEND=qdrant          |

## 5. Streaming

`api/websockets/voice_stream.py` opens a single WS for both directions:

1. Client streams 16 kHz mono PCM frames → `StreamingSTT.feed()`.
2. On utterance boundary → `flush_segment()` returns finalized text.
3. Text is fed into the graph via `astream_events`.
4. As soon as `accessibility_node` emits its first chunk, `stream_tts`
   begins synthesizing audio frames; we forward them as binary WS frames.
5. `tts_node` final write closes the response turn.

End-to-end "first audio out" latency target: **< 1.5 s** on warm GPU.

## 6. Observability

- **LangSmith** traces: enabled by setting `LANGCHAIN_TRACING_V2=true`
  and a `LANGSMITH_API_KEY`. Traces are tagged with the session_id.
- **Prometheus** at `/metrics`. Custom counters / histograms for:
  STT latency, LLM tokens, quiz attempts, intent distribution.
- **Structured JSON logs** with `session_id` and `student_id` context.
