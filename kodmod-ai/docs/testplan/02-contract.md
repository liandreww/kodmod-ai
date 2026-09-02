# Stage 2 — Contract / Schema

**Tujuan.** Memastikan *bentuk* benar sebelum menyentuh I/O: skema Pydantic (`models/*`),
konsistensi handler ↔ `response_model`, `/openapi.json` ter-generate, dan **graph
ter-compile dengan semua node reachable dari `START`**.

**Sifat gate.** Blok. Cepat (< 30 s), tanpa DB/Redis/LLM (LLM di-stub bila `build_kodmod_graph`
menyentuh getter saat wiring — biasanya tidak).

**Framework.** `pytest`, `fastapi.testclient.TestClient` (hanya untuk `app.openapi()` &
introspeksi rute — **tanpa** lifespan/DB), `pydantic`, util BFS graph.

**Entry.** Stage 1 hijau. **Exit.** Semua hijau; `xfail(strict)` untuk mismatch yang
diketahui (quiz fields, reachability) terdaftar di `traceability.md`.

**Lokasi.** `tests/contract/`. **Marker.** `contract`.

---

## 1. Skema Pydantic — `models/*`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-CONTRACT-001 | `StudentCreate` valid | payload minimal sah | objek terbentuk; default `voice_settings` | `models/student.py` | — |
| KM-CONTRACT-002 | `StudentCreate` invalid | `preferred_language="fr"` | `ValidationError` | Literal | — |
| KM-CONTRACT-003 | `StudentOut.from_attributes` | ORM `Student` dummy → `StudentOut.model_validate` | field lengkap termasuk `created_at/updated_at` | `from_attributes=True` | — |
| KM-CONTRACT-004 | `StudentProfileOut` | dgn `overall_mastery, weak_concepts, strong_concepts, streak_days, last_active_at` | valid | model | — |
| KM-CONTRACT-005 | `QuizStartRequest` | `student_id:UUID`, `n_questions` 1..20, `difficulty` Literal | valid & batas ditegakkan (`0`, `21` → error) | `models/quiz.py` | — |
| KM-CONTRACT-006 | `QuizStartResponse` bentuk | konstruksi dgn `quiz_session_id:UUID, first_question:QuizQuestionOut, total_questions:int` | valid | model | #5 |
| KM-CONTRACT-007 | `QuizSubmitRequest` | field `quiz_session_id, question_id, student_answer, response_latency_ms?, transcribed_from_audio` | valid; nama field persis | model | #5 |
| KM-CONTRACT-008 | `QuizSubmitResponse` | `score` 0..1, `is_correct`, `feedback`, `quiz_complete=False`, `cumulative_score=0.0` | valid & default | model | #5 |
| KM-CONTRACT-009 | `ContentRetrieveRequest` | `query`, `top_k` 1..20 default 5, `language` default `id` | valid & batas | `models/content.py` | — |
| KM-CONTRACT-010 | `ContentRetrieveResponse` | `chunks: list[dict]`, `query` | valid | model | — |
| KM-CONTRACT-011 | `ExerciseGenerateRequest/Response` | round-trip | valid | model | — |
| KM-CONTRACT-012 | `ConceptOut/LessonOut/ExerciseOut` | dari ORM dummy | `model_validate` sukses | model | — |
| KM-CONTRACT-013 | `models/session.py` (tak terpakai rute) | round-trip | valid — **dicatat** sebagai dead schema di traceability | model | — |
| KM-CONTRACT-014 | Semua model: `model_json_schema()` | loop seluruh kelas di `models/` | tidak raise | pydantic | — |
| KM-CONTRACT-015 | Enum/Literal graph state | `Intent`, `DifficultyLevel`, `EmotionalState`, `NextAction` — nilai persis sesuai `graphs/state.py` | daftar cocok snapshot | state.py | — |

## 2. Konsistensi API

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-CONTRACT-020 | Handler quiz ↔ `response_model` | inspeksi `api/routes/quiz.py`: kwargs yang dipakai handler saat mengonstruksi response vs field `QuizStartResponse`/`QuizSubmitResponse` | **cocok** (target). Saat ini handler pakai `session_id/first_question/question_audio_uri/feedback_text/feedback_audio_uri/is_session_complete/cumulative_score` yang tak ada di model → `xfail(strict)` | model vs handler | #5 |
| KM-CONTRACT-021 | Handler quiz baca field request | inspeksi: `body.session_id`, `body.answer_text` vs model punya `quiz_session_id`, `student_answer` | target: nama cocok → `xfail(strict)` | model vs handler | #5 |
| KM-CONTRACT-022 | `_load_mastery` bukan chain coroutine | AST/inspeksi `api/routes/quiz.py::_load_mastery` | target: tidak `StudentModel.load(id).mastery_scores()` (dua coroutine dirantai) → `xfail(strict)` | kode | #6 |
| KM-CONTRACT-023 | `/openapi.json` valid | `app.openapi()` | dict OpenAPI 3.x; tidak raise | FastAPI | — |
| KM-CONTRACT-024 | Setiap rute punya `summary`/`description` | loop `app.routes` | semua non-kosong (yang kosong → daftar di laporan; `xfail` bila jadi kebijakan) | inventaris | — |
| KM-CONTRACT-025 | Inventaris rute vs `docs/API.md` | bandingkan path+method terdaftar dgn `docs/API.md` | selisih di-flag; path health nyata `/live`,`/ready`,`/version` (bukan `/health/*`) | `api/main.py` mount | #13 |
| KM-CONTRACT-026 | Prefix router benar | `voice`→`/voice`, `quiz`→`/quiz`, dst; `health` tanpa prefix; `voice_stream`→`/ws` | cocok `include_router` | `api/main.py` | — |
| KM-CONTRACT-027 | `/metrics` ter-mount tanpa auth | ada di `app.routes`, tidak ada dependency auth | inventaris | #14 (dicatat, ditindak di Stage 4/9) |
| KM-CONTRACT-028 | Import `api/routes/exercise.py` | import modul | **saat ini** `ImportError: generate_questions_for_student` → `xfail(strict)` | modul | #7 |

## 3. Wiring graph — `graphs/main_graph.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-CONTRACT-030 | Compile async | `g = await build_kodmod_graph(checkpointer=None)` | sukses; `g.ainvoke` & `g.astream_events` ada | **perbaiki `test_graph_wiring.py`** (dulu tanpa `await`) | #18 |
| KM-CONTRACT-031 | Set node persis 15 | introspeksi `g.get_graph().nodes` | nama = {stt, intent_router, rag_retrieval, tutoring, mini_quiz, problem_generator, quiz_ask, scoring, quiz_analyzer, update_student_model, analytics, recommendation, accessibility, reflection, tts} | daftar node | — |
| KM-CONTRACT-032 | Reachability semua node dari START | BFS pada edge (termasuk cabang conditional) dari `START` | **semua** node terjangkau. Saat ini `mini_quiz` tak punya inbound edge; `scoring`/`quiz_analyzer`/`update_student_model` tak terjangkau dari `START` → `xfail(strict)` | struktur graph | #11, bug 3 |
| KM-CONTRACT-033 | Tidak ada node yatim tanpa outbound | tiap node non-`END` punya ≥1 outbound edge/cabang | terpenuhi | struktur | — |
| KM-CONTRACT-034 | `interrupt_after` bersyarat | compile dgn checkpointer dummy vs `None` | `["reflection"]` vs `[]` | kode compile | — |
| KM-CONTRACT-035 | Conditional router target valid | tiap nilai balik `route_after_intent/scoring/analyzer` adalah nama node yang benar-benar ada (mis. `end_speak` → mapping ke `tts`) | tak ada target menggantung | mapping conditional edges | — |
| KM-CONTRACT-036 | `run_turn` generator | `run_turn(g, state, config)` adalah async generator yang meneruskan `astream_events(version="v2")` | tipe benar | kode | — |
| KM-CONTRACT-037 | `rag_retrieval_node` kontrak keluaran | inspeksi: node mengisi `retrieved_docs` **dan** `next_action`/`last_node` | target → `xfail(strict)` (kini hanya `retrieved_docs`) | node vs konvensi | #10 |
| KM-CONTRACT-038 | `rag_retrieval_node` baca konsep | inspeksi: baca `current_concept_id` (bukan `state["concept_id"]` yang tak pernah di-set) | target → `xfail(strict)` | node | #10 |

---

## Catatan implementasi

- Stage ini **tidak** menjalankan lifespan `api/main.py` (yang butuh Postgres + checkpointer).
  Gunakan `app = importlib.import_module("api.main").app` lalu hanya panggil `app.openapi()` /
  iterasi `app.routes`. Bila import `api.main` memicu efek samping berat, gunakan
  `fastapi.FastAPI` + `include_router` manual meniru `api/main.py` (dicatat sebagai util test).
- BFS reachability: bangun dari `g.get_graph()` (`nodes`, `edges`) plus daftar target
  conditional edges (LangGraph mengekspos ini via `get_graph()` — kalau tidak lengkap,
  parse `route_after_*` mapping dict langsung).
- Semua `xfail(strict=True)` di sini adalah **kontrak yang harus dipenuhi sebelum Stage 3–6
  bisa hijau**; mereka adalah pekerjaan perbaikan paling awal setelah Stage 0–1.
