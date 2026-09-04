# Traceability Matrix — Requirement / Bug → Test ID → Stage

Setiap baris **wajib** punya ≥ 1 Test ID (gate KM-READY-009). Kolom "Isu perbaikan" diisi
saat backlog dibuat.

Legenda stage: 0=static 1=unit 2=contract 3=integration 4=api 5=ws 6=e2e 7=system 8=perf 9=security.

---

## A. Bug berlapis utama (`docs/LAPORAN_BUG.md`)

| Kode | Deskripsi | Test ID (deteksi pertama → verifikasi) | Stage | Target rilis | Isu perbaikan |
|---|---|---|---|---|---|
| BUG-1 | `agents/tutoring_agent.py` import `StudentProfileTool`/`RAGTool` tak ada → `ImportError` saat `build_kodmod_graph` | KM-STATIC-010, KM-STATIC-011 → KM-CONTRACT-030, KM-INT-103 | 0→2→3 | ✅ | — |
| BUG-2 | `database/session.py` `conn.execute("SELECT 1")` string mentah → `ObjectNotExecutableError` | KM-INT-001 | 3 | ✅ | — |
| BUG-3 | Jalur kuis (`scoring→quiz_analyzer→update_student_model`) tak ter-wire dari `START`; `mini_quiz` orphan; `route_after_intent` tanpa cabang "quiz in progress"; nama router vs attach point tertukar | KM-CONTRACT-032 → KM-INT-101, KM-INT-150..154 → KM-E2E-002 | 2→3→6 | ✅ | — |

### Catatan run Stage 0 (2026-09-02)

- **KM-STATIC-011 import-smoke sudah hijau** untuk `agents.tutoring_agent` (BUG-1),
  `api.routes.exercise` (#7), `tools.rag_tool` (#9) — modul-modul itu meng-*import*
  bersih sekarang (`KNOWN_DEAD` dikosongkan). #7 (`generate_questions_for_student`
  hilang) & #9 (`Tool()` kurang arg) masih nyata tapi tertangkap mypy/contract, bukan
  import.
- **KM-STATIC-003 (mypy inti) ditandai `@pytest.mark.known_bug`** (kebijakan 2026-09-02 —
  bukan lagi `xfail`): asersi biasa, jadi **MERAH** di `pytest -m static` selama backlog
  ada, dan **HIJAU** begitu semua error beres — tak ada penanda `xfail` untuk dicabut.
  Runner stage pakai `-m "static and not slow and not known_bug"` supaya Stage 0 tetap
  menggerbang regresi; `make test-burndown` menghitung sisa. Sama untuk KM-STATIC-004
  (mypy `tests/`) & KM-STATIC-060 (alembic `versions/` kosong).
  - **Progres 2026-09-02:** ~62 → ~51 error. #2 (`student.language`) & #6 (`_load_mastery`
    rantai coroutine) di-fix; plus ~9 error type-hint murni (aman, tanpa ubah perilaku):
    `scoring_agent._build_attempt/_score_with_rubric/_semantic_similarity` (`QuizQuestion`
    vs `dict`, ndarray reassign), `api/routes/content.py`+`exercise.py` return
    `Sequence`→`list(...)`, `rag/ingestion.py` conditional-import `store` (`# type: ignore[no-redef]`).
    Sisa = struktural bertarget-stage: #1 `Student.profile`, #4 `stream_tts`, #5 quiz field
    mismatch, #7 `generate_questions_for_student`, `UUID`→`str` di `initial_state`,
    friksi stub lib di `tools/llm_client.py`, `voice/tts.py`, `voice/stt.py::_ensure_local`
    (missing `await`, jalur SSRF — Stage 9).
- **KM-STATIC-030**: 2 CVE `tornado 6.5.x` (GHSA-wwv5-g3v4-889x, GHSA-8423-8fgw-73vq)
  di-*waive* bertanggal di `.pip-audit-ignore` — masuk hanya via JupyterLab lokal,
  bukan `requirements.txt`/image. Tinjau ulang di Stage 10.

### Catatan run Stage 5 (2026-09-02)

- **#WS-AUTH** (`voice_ws` memanggil `authenticate_ws(websocket)` sebagai fungsi biasa,
  bukan `Depends`, sehingga `token: str | None = Query(default=None)` tak pernah di-resolve →
  setiap handshake 401) **beres**: `authenticate_ws` kini membaca `?token=`/header sendiri.
  Bersama #17/#21/#4 dan resume graph melewati `interrupt_after=["reflection"]`, seluruh
  `pytest -m ws` hijau (19 passed) kecuali **KM-WS-022 `skip`** — setelah perbaikan tak ada
  jalur 1011 yang bisa dipicu klien (non-JSON diabaikan per KM-WS-024; frame besar close 1009
  per KM-WS-040; graph stub selalu selesai). Ketahanan error internal tercakup
  KM-WS-020/021/024/040. `tests/ws/` tak lagi punya test `known_bug`.
- Setting baru `WS_MAX_FRAME_BYTES` (default 1 MiB) — batas per-frame masuk di `/ws/voice`.

## B. Temuan eksplorasi (#1..#20)

| # | Deskripsi | Test ID | Stage | Target rilis | Isu perbaikan |
|---|---|---|---|---|---|
| #1 | `Student.profile` diakses di `voice.py`(×2), `quiz.py`(×2), `voice_stream.py` — atribut tak ada | KM-API-070, KM-API-080, KM-API-083, KM-WS-014, KM-E2E-001, KM-E2E-002 | 4,5,6 | ✅ | — |
| #2 | `voice_stream.py` `student.language` → harus `preferred_language` | KM-WS-013 | 5 | ✅ **FIXED** (2026-09-02) — `student.preferred_language or "id"`; verifikasi runtime di Stage 5 (KM-WS-013) | — |
| #3 | `_collect_utterance` unpack `stt.feed()` sbg 2-tuple; nyatanya `dict` | KM-WS-011 | 5 | ✅ | — |
| #4 | `stream_tts(websocket, text)` — signature `(text, voice=None)->AsyncIterator[bytes]`, hasil tak di-iterate | KM-WS-012 | 5 | ✅ | — |
| #5 | `api/routes/quiz.py` field request/response ≠ `models/quiz.py` (`session_id`/`answer_text`/`feedback_text`/...) | KM-CONTRACT-020, KM-CONTRACT-021, KM-API-072, KM-API-073, KM-E2E-002 | 2,4,6 | ✅ | — |
| #6 | `_load_mastery` merantai dua coroutine (`StudentModel.load(id).mastery_scores()`) | KM-CONTRACT-022, KM-API-071 | 2,4 | ✅ **FIXED** (2026-09-02) — `model = await StudentModel.load(id); return await model.mastery_scores()`; verifikasi di Stage 2/4 | — |
| #7 | `api/routes/exercise.py` import `agents.problem_generator.generate_questions_for_student` (tak ada) | KM-STATIC-010, KM-CONTRACT-028, KM-API-062 | 0,2,4 | ✅ | — |
| #8 | `get_recommendation_llm(temperature=...)` di `insights.py` & `get_tutor_llm(temperature=...)` di `narration.py` — getter `@lru_cache` tanpa arg | KM-UNIT-123, KM-UNIT-133, KM-INT-115, KM-INT-118 | 1,3 | ✅ **FIXED** (Stage 1, 2026-09-02) — kedua call site kini panggil getter tanpa arg; temperature dikonfigurasi di getter | — |
| #9 | `tools/rag_tool.py` import `QdrantStore` dari `rag.stores.qdrant_store` (tak ada); env `KODMOD_VECTOR_STORE` ≠ `VECTOR_BACKEND` | KM-STATIC-010, KM-SYS-021 | 0,7 | ✅ | — |
| #10 | `rag/retriever.rag_retrieval_node` baca `state["concept_id"]` (tak pernah di-set); tak isi `next_action`/`last_node` | KM-CONTRACT-037, KM-CONTRACT-038, KM-INT-091 | 2,3 | ✅ | — |
| #11 | Graph: `mini_quiz` tanpa inbound; jalur jawab-kuis→skor unreachable dari `START` (= BUG-3) | KM-CONTRACT-032, KM-INT-150..154, KM-E2E-002, KM-PERF-002 | 2,3,6,8 | ✅ | — |
| #12 | `route_after_scoring` hardcode `0.6` (abaikan `settings.QUIZ_PASS_THRESHOLD`); di-attach ke node `quiz_analyzer` | KM-UNIT-063, KM-INT-152 | 1,3 | ✅ **FIXED** (Stage 1, 2026-09-02) — `threshold = settings.QUIZ_PASS_THRESHOLD`. Attach-point ke `quiz_analyzer` masih perlu diverifikasi di Stage 3 (KM-INT-152). | — |
| #13 | `health` router di-mount tanpa prefix `/health`; path nyata `/live`,`/ready`,`/version`; Dockerfile healthcheck `/health/live` | KM-API-001, KM-API-006, KM-CONTRACT-025, KM-SYS-001 | 2,4,7 | ✅ (samakan path + dok) | — |
| #14 | Tanpa auth: `POST /student`, `GET /student/{id}/profile`, semua `/content/*`, `GET /exercise/by-concept/{id}`, `/metrics` | KM-API-030, KM-SEC-010, KM-SEC-013, KM-SEC-062, KM-SYS-031 | 4,7,9 | ✅ (auth atau allowlist sadar) | — |
| #15 | `.env` on-disk berisi `OPENAI_API_KEY`+`JWT_SECRET` asli; model `gpt-5.6-luna` tak terverifikasi; `EMBEDDING_DIM=1536` vs `vector(1024)` | KM-STATIC-021, KM-STATIC-022, KM-SEC-014, KM-SEC-070..072, KM-SYS-041 | 0,7,9 | ✅ (rotasi) | — |
| #16 | `_decode_jwt` → `uuid.UUID(sub)` tak dijaga → `ValueError`/500; tanpa `aud`/`iss`/`nbf` | KM-API-013, KM-SEC-005, KM-SEC-006 | 4,9 | ✅ | — |
| #17 | `authenticate_ws` hanya `?token=`, bukan header (docstring salah) | KM-WS-006 | 5 | ✅ **FIXED** (2026-09-02) — `authenticate_ws` membaca `?token=` lalu fallback ke header `Authorization: Bearer`; docstring modul WS disamakan | — |
| #18 | Test lama broken: `test_student_model.py` (signature usang), `test_graph_wiring.py` (tanpa `await`, `initial_state` kurang `session_id`) | KM-UNIT-020..030, KM-CONTRACT-030, KM-STATIC-051 | 0,1,2 | ✅ | — |
| #19 | `voice/tts.py` `OUTPUT_DIR.mkdir()` saat import (kini di-try/except) | KM-STATIC-011, KM-INT-124 | 0,3 | ✅ | — |
| #20 | `ClassroomAggregator` butuh `classroom_enrollment` (hanya di `schema.sql`, bukan ORM) | KM-INT-078, KM-INT-079, KM-API-094, KM-API-095, KM-E2E-004 | 3,4,6 | ✅ (tambah model ORM `ClassroomEnrollment` **atau** relasi ORM) | — |
| #21 | `api/websockets/voice_stream.py` menginstansiasi `StreamingSTT` langsung, tidak memeriksa `settings.STT_ENABLED` (beda dari `stt_node`) — WS selalu mencoba STT audio nyata bahkan di text-mode; ditemukan saat mendesain pengujian WS black-box terhadap proses `api` host sungguhan | KM-WS-010, KM-WS-030, KM-WS-041 | 5 | ✅ **FIXED** (2026-09-02) — `StreamingSTT` hanya dibangun saat `STT_ENABLED`; frame `end_of_speech` menerima field `transcript` opsional yang dipakai langsung; `_collect_utterance` juga: guard ukuran frame (`WS_MAX_FRAME_BYTES`→close 1009), abaikan teks non-JSON, unpack `feed()` sebagai dict. Plus `voice_ws` melanjutkan graph melewati `interrupt_after=["reflection"]` supaya `accessibility`/`tts` jalan. | — |
| #22 | `database/session.py::_make_engine()` selalu mengirim `pool_size`/`max_overflow` ke `create_async_engine()` meski `poolclass=NullPool` dipasang saat `ENV=test` — `NullPool` tak mendukung parameter itu → `TypeError`, `init_db()` gagal total, memblokir SEMUA yang butuh DB (`db-init`, Stage 3+). Ditemukan saat menjalankan `db-init` sungguhan di container (`ENV=test`) — sebelumnya tak pernah tereksekusi end-to-end. **Sudah diperbaiki** (kirim `pool_size`/`max_overflow` hanya saat bukan `NullPool`) | KM-INT-001, KM-STATIC-045 (build & boot smoke) | 0, 3 | ✅ **FIXED** (lihat commit terkait) | — |
| #23 | `agents/scoring_agent.py::_score_mcq` dengan `expected_answer` kosong: kondisi `s.endswith(e)` = `s.endswith("")` selalu `True` → mengembalikan `(1.0, "Benar.")` untuk jawaban apa pun alih-alih `(0.0, ...)` yang aman. Tak crash (bukan IndexError), tapi skor salah. Ditemukan saat menulis KM-UNIT-043. | KM-UNIT-043 | 1 | ✅ **FIXED** (Stage 1, 2026-09-02) — `if not e: return 0.0, "Belum tepat."` sebelum cek `endswith`. | — |

## C. Appendix `LAPORAN_BUG.md` L-1..L-16

| Kode | Ringkas | Test ID | Stage | Target rilis |
|---|---|---|---|---|
| L-1 | (lihat `docs/LAPORAN_BUG.md`) — impor/wiring | KM-STATIC-010/011 | 0 | ✅ |
| L-2 | idem kategori runtime import | KM-STATIC-011 | 0 | ✅ |
| L-3 | idem | KM-STATIC-011, KM-INT-100..124 | 0,3 | ✅ |
| L-4 | idem | KM-INT-100..124 | 3 | ✅ |
| L-5 | `database/schema.sql` ≠ `database/models.py` (kolom `concepts.id`, `mastery_scores.*`, `students.display_name`) | KM-INT-004, KM-INT-007, KM-INT-011 | 3 | ✅ (deprecate `schema.sql`) |
| L-6 | runtime `AttributeError`/`TypeError` di `api/routes/*` | KM-API-062/070/072/080 | 4 | ✅ |
| L-7 | `voice/tts.py` `mkdir` import-time `PermissionError` (fixed working tree) | KM-STATIC-011, KM-INT-124 | 0,3 | ✅ |
| L-8..L-13 | `analytics_agent`, `accessibility` LLM getter dgn arg, `student.profile` di route | KM-UNIT-123/133, KM-INT-113/115/118, KM-API-070/080 | 1,3,4 | ✅ |
| L-14 | `test_graph_wiring.py` tak `await`; `initial_state` kurang `session_id` | KM-CONTRACT-030, KM-UNIT-071 | 1,2 | ✅ |
| L-15 | `test_student_model.py` signature `update()` usang → `TypeError` | KM-UNIT-020..030 | 1 | ✅ |
| L-16 | `config/settings.py` `CORS_ALLOW_ORIGINS: List[str]` + `.env` `*` → `SettingsError` (fixed via `enable_decoding=False`) | KM-STATIC-012, KM-STATIC-013 | 0 | ✅ |

## D. Requirement fungsional → Test ID

| Req | Deskripsi | Test ID |
|---|---|---|
| RF-01 | Satu turn = satu invokasi graph; `stt→intent_router→…→accessibility→tts` | KM-INT-140..146, KM-E2E-001 |
| RF-02 | Mid-quiz, utterance berikut dipaksa `intent="quiz"` dgn `student_answer`, kecuali meta-command | KM-INT-101, KM-INT-102, KM-INT-150..154 |
| RF-03 | Persistensi checkpoint per node, bertahan restart | KM-INT-144/145, KM-SYS-010/011 |
| RF-04 | HITL `interrupt_after=["reflection"]` saat checkpointer ada | KM-CONTRACT-034, KM-INT-145, KM-SYS-011 |
| RF-05 | Output tutor audio-only: tanpa referensi visual, kalimat ≤ 22 kata, angka dieja, SSML | KM-UNIT-080..090, KM-INT-117/118, KM-E2E-010 |
| RF-06 | BKT mastery: benar↑ / salah↓, decay harian, batas [0,1] | KM-UNIT-020..030, KM-INT-060..065, KM-E2E-002 |
| RF-07 | RAG: chunk → embed → retrieve → rerank; pgvector & qdrant | KM-UNIT-010..018/150..152, KM-INT-080..098, KM-SYS-020/021 |
| RF-08 | Analytics siswa & kelas + ringkasan lisan Bahasa Indonesia | KM-UNIT-110..123, KM-INT-070..079, KM-E2E-003/004 |
| RF-09 | Auth JWT: `current_student`/`current_teacher`; WS `?token=` | KM-API-010..021, KM-WS-001..006, KM-SEC-001..015 |
| RF-10 | LLM via role getter; provider switch `anthropic/openai/ollama/vllm` | KM-UNIT-130..134, KM-STATIC-014 |
| RF-11 | Config satu sumber (`settings`); import aman env bersih & `.env.example` | KM-STATIC-012..015 |
| RF-12 | Infra (DB, Redis, llm-stub) di satu Docker Compose project `kodmod-test`; `db-init` & `api` reproducible di host (`scripts/create_test_db`, `scripts/seed_curriculum`, `scripts/serve_test_api`) | KM-STATIC-040..047, KM-SYS-001..004, KM-SYS-052 |

## E. Non-functional → Test ID

| NFR | Deskripsi | Test ID |
|---|---|---|
| NFR-P1 | Throughput/latency turn tutoring (overhead framework, stub LLM) | KM-PERF-001, KM-PERF-005 |
| NFR-P2 | Batas connection pool & checkpointer write | KM-PERF-010, KM-PERF-011 |
| NFR-P3 | Tanpa kebocoran resource (soak 30 min) | KM-PERF-030, KM-PERF-031 |
| NFR-P4 | Konkurensi WebSocket | KM-PERF-020, KM-PERF-021 |
| NFR-S1 | 0 CVE High/Critical dependensi & image | KM-STATIC-030/031, CI trivy/gitleaks |
| NFR-S2 | Tanpa injeksi SQL di jalur raw SQL | KM-SEC-020..026 |
| NFR-S3 | Tanpa SSRF via fetch audio | KM-SEC-030..034 |
| NFR-S4 | Ketahanan DoS (body/upload/WS/rate-limit) | KM-SEC-040..047 |
| NFR-S5 | Tanpa kebocoran rahasia (log/respons/image) | KM-SEC-070..072, KM-SYS-041 |
| NFR-O1 | `/metrics` Prometheus, log JSON, shutdown anggun | KM-SYS-030/040/050 |
| NFR-Q1 | Coverage & order-independence | KM-READY-001/002/010 |
