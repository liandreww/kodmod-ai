# Stage 3 — Integration

**Tujuan.** Membangun & memverifikasi fondasi data: DB layer, memory (Postgres+Redis),
analytics, RAG store, tiap agent node terisolasi, lalu graph utuh per intent — semua dengan
**infra nyata** (Postgres+pgvector, Redis) tetapi **LLM & embedding di-stub**.

**Sifat gate.** Blok. 2–5 menit.

**Framework.** `pytest` + `pytest-asyncio`, fixture `db_engine`/`db_session` (SAVEPOINT
rollback), `redis_client` (`flushdb`), `stub_llms`/`stub_embeddings` autouse,
`AsyncPostgresSaver` pada DB test untuk test graph berpersisten.

**Entry.** Stage 2 hijau; infra naik
`docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub`;
lalu di host `python -m scripts.init_test_db` (schema + seed, env test terkunci) selesai.
**Exit.** Semua hijau kecuali `xfail(strict)` yang tercatat (quiz multi-turn,
`classroom_enrollment`, `rag_retrieval_node`).

**Lokasi.** `tests/integration/`. **Marker.** `integration`, `db`, `redis`.

---

## 1. DB layer — `database/session.py`, `scripts/create_test_db.py`, `database/models.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-001 | `init_db` smoke `SELECT 1` | `await init_db()` terhadap Postgres test (`ENV=test` → `NullPool`) | sukses; `_engine` & `_session_factory` ter-set; `text("SELECT 1")` jalan (bukan string mentah); `_make_engine()` tidak kirim `pool_size`/`max_overflow` saat `NullPool` dipakai (dulu `TypeError`, sudah diperbaiki) | `database/session.py` | bug 2, #22 |
| KM-INT-002 | `init_db` idempoten | panggil 2× | tidak buat engine kedua | kode | — |
| KM-INT-003 | `NullPool` saat `ENV=test` | inspeksi `get_engine().pool` | `NullPool` | kode `use_null_pool` | — |
| KM-INT-004 | `create_test_db` bikin semua tabel ORM | jalankan lalu introspeksi `information_schema.tables` | semua tabel dari `Base.metadata` ada | `Base.metadata.create_all` | L-5 |
| KM-INT-005 | `curriculum_chunks` DDL | introspeksi kolom + `vector_dims` | `embedding vector(1024)`, indeks HNSW `vector_cosine_ops`, btree `concept_id`/`source` | `_DDL` | — |
| KM-INT-006 | Ekstensi aktif | `SELECT extname FROM pg_extension` | `vector`, `pgcrypto` | `_DDL` | — |
| KM-INT-007 | Kolom ORM == kenyataan | untuk `mastery_scores` cek kolom `mastery, confidence, n_attempts, last_seen`; `students` cek `full_name, accessibility_profile, preferred_language, voice_settings` | cocok ORM (**bukan** `schema.sql` yang punya `score`/`last_practiced`/`display_name`) | `database/models.py` | L-5 |
| KM-INT-008 | `async_session` commit/rollback | tulis lalu raise di dalam `async with` | rollback; di luar exception → commit | context manager | — |
| KM-INT-009 | `get_db` dependency generator | konsumsi generator | commit di akhir bersih, rollback saat error | kode | — |
| KM-INT-010 | `close_db` | `await close_db()` | engine `dispose`, global reset ke `None` | kode | — |
| KM-INT-011 | `schema.sql` ditandai deprecated | test dokumentasi: assert compose test **tidak** mount `schema.sql`; komentar rujuk ke keputusan | keputusan plan | L-5 |

## 2. memory/long_term — Postgres

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-020 | `load_profile` siswa baru | seed `Student`, `load_profile(id)` | `dict` dgn `full_name, preferred_language, accessibility_profile, voice_settings, mastery={}, streak_days=0` | fungsi | — |
| KM-INT-021 | `update_mastery` upsert | 2× `update_mastery(student, concept, ...)` | 1 baris (`ON CONFLICT (student_id,concept_id)` `uq_student_concept`), nilai terupdate | pg upsert | — |
| KM-INT-022 | `fetch_weak_concepts` | seed 6 mastery beda | 5 terlemah, `list[dict{concept_id,mastery}]` naik | fungsi | — |
| KM-INT-023 | `_compute_streak` | seed `LearningSession` beruntun & bolong | hitung streak benar | fungsi | — |
| KM-INT-024 | `record_misconception` + `fetch_open_misconceptions` | catat lalu ambil | muncul; `resolved=False` | fungsi | — |
| KM-INT-025 | `log_interaction` | tulis dgn `metadata` | tersimpan di kolom `"metadata"` (mapped `metadata_`) | ORM `InteractionLog` | — |
| KM-INT-026 | `store_recommendation` + `fetch_active_recommendations` | simpan 6, ambil `limit=5` | 5 teratas aktif | fungsi | — |

## 3. memory/short_term — Redis

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-040 | `set_value`/`get_value` | set lalu get key `kodmod:session:{sid}:{sub}` | nilai sama; TTL ~24 j | fungsi | — |
| KM-INT-041 | `delete_session` SCAN+DEL | isi 3 sub-key, `delete_session(sid)` | semua terhapus | fungsi | — |
| KM-INT-042 | `store_last_response`/`fetch_last_response` | round-trip | sama | fungsi | — |
| KM-INT-043 | `append_tutoring_turn` LTRIM 12 | append 15 turn | `fetch_tutoring_turns` kembalikan 12 terakhir; EXPIRE ter-set | pipeline RPUSH+LTRIM+EXPIRE | — |
| KM-INT-044 | `set_pacing`/`get_pacing` fallback | tanpa set → get | default `settings.TTS_RATE` | fungsi | — |
| KM-INT-045 | `get_redis` pool reuse | 2× `get_redis()` | pool sama; `close_redis()` bersih | modul `_pool` | — |

## 4. memory/episodic — Postgres (`analytics_reports`)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-050 | `record_episode` | catat `kind="milestone"` | baris `analytics_reports` `report_type="episode:milestone"`, payload utuh | fungsi | — |
| KM-INT-051 | `fetch_recent_episodes` filter | campur report biasa + episode | hanya `report_type LIKE 'episode:%'` | fungsi | — |
| KM-INT-052 | `maybe_record_mastery_unlock` | mastery lewat 0.8 | 1 episode `mastery_unlocked` | ambang 0.8 | — |
| KM-INT-053 | `maybe_record_struggle` | 3 kegagalan beruntun | 1 episode `concept_struggled` | ambang 3 | — |

## 5. analytics/student_model — round-trip DB

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-060 | `StudentModel.load` SQL | seed `mastery_scores`, `await StudentModel.load(uuid)` | `_scores/_confidence/_attempts/_last_practiced` terisi; SQL `mastery AS score`, `last_seen AS last_practiced`, `CAST(:sid AS uuid)` jalan | fungsi | — |
| KM-INT-061 | `load` siswa tanpa baris | uuid acak | model kosong, tidak raise | fungsi | — |
| KM-INT-062 | `update` → `persist` round-trip | load → `update("c",1.0)` → `persist()` → load ulang | nilai persisten cocok; `INSERT ... ON CONFLICT (student_id,concept_id) DO UPDATE` | fungsi | — |
| KM-INT-063 | `persist` set `n_attempts`, `last_seen` | idem | kolom terupdate | fungsi | — |
| KM-INT-064 | `mastery_scores()` async | `await m.mastery_scores()` | `dict[str,float]` salinan | fungsi | — |
| KM-INT-065 | `update_student_model_node` tulis DB | state dgn `quiz_attempts`+`quiz_questions`, `await update_student_model_node(state)` | `mastery_scores` di state & `mastery_scores` table terupdate; `next_action="generate_analytics"` | node | #8 (cek getter tak dipakai dgn arg) |

## 6. analytics/aggregator — DB

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-070 | `StudentAggregator.summarise` dataset seeded | seed sesi/attempt/mastery/misconception/interaction, `summarise(student_id=, window="week")` | `n_sessions, total_minutes, n_attempts, n_correct, avg_score, accuracy, mastery[], weak(5), strong(5), overall_mastery, engagement_index` benar | rumus di kode | — |
| KM-INT-071 | `engagement_index` rumus | dataset terkontrol | `min(1.0, sessions_per_day*(total_minutes/max(1,n_sessions))/30.0)` | rumus | — |
| KM-INT-072 | `student_not_found` | uuid acak | `{"error":"student_not_found"}` | kode | — |
| KM-INT-073 | `include_recommendations` | flag True | `active_recommendations` diisi dari `memory.long_term` | kode | — |
| KM-INT-074 | `_window_start` semua window (integrasi) | today/week/month/all | filter tanggal query sesuai | `_window_start` | — |
| KM-INT-078 | `ClassroomAggregator.summarise` | seed classroom + siswa | **butuh tabel `classroom_enrollment`** (hanya di `schema.sql`, tak ada di ORM) → `xfail(strict)`; target: roster jalan, rata-rata kelas + `class_weak_concepts` top-5 | kode + skema | #20 |
| KM-INT-079 | `classroom_not_found` | uuid acak | `{"error":"classroom_not_found"}` | kode | #20 (xfail bersama) |

## 7. RAG store — pgvector (`rag/stores/pgvector_store.py`)

Embedding = stub deterministik 1024-dim.

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-080 | `upsert_chunks` insert | 5 record | 5 baris `curriculum_chunks`; `embedding` ter-CAST ke `vector` | SQL | — |
| KM-INT-081 | `upsert_chunks` konflik id | upsert ulang id sama, konten beda | `ON CONFLICT (id) DO UPDATE` — konten terbarukan, tetap 5 baris | SQL | — |
| KM-INT-082 | `query` cosine | query vektor dekat salah satu chunk | chunk itu skor tertinggi; `score = 1-(embedding <=> :emb)` | SQL | — |
| KM-INT-083 | `query` filter `concept_id` | 2 concept | hanya chunk concept yang diminta | SQL | — |
| KM-INT-084 | `query` filter `language` | id vs en | sesuai | SQL | — |
| KM-INT-085 | `query` `top_k` | `top_k=3` | ≤ 3 hasil, urut skor turun | SQL | — |
| KM-INT-086 | `PgVectorStore.similarity_search` | `filters={"concept_id": "<uuid str>"}` | parse ke UUID, hasil terfilter | kelas | — |
| KM-INT-087 | `delete_by_source` | hapus by `source` | baris hilang, kembalikan jumlah | SQL | — |
| KM-INT-088 | Indeks HNSW dipakai | `EXPLAIN` query | rencana pakai `idx_cc_embedding_hnsw` (atau catat bila seq-scan pada dataset kecil) | pg planner | — |

## 8. RAG retriever & ingestion

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-091 | `rag_retrieval_node` baca `current_concept_id` & isi `next_action` | state dgn `transcribed_text` + `current_concept_id` | `retrieved_docs` terisi **dan** `next_action`/`last_node` di-set; membaca `current_concept_id` bukan `state["concept_id"]` → `xfail(strict)` | konvensi node | #10 |
| KM-INT-092 | `retrieve("")` | query kosong | `[]` | kode | — |
| KM-INT-093 | `retrieve()` end-to-end | ingest 3 chunk, `retrieve("pecahan adalah", top_k=5)` | hasil relevan, ≤ `rerank_top_k` bila reranker jalan | kode | — |
| KM-INT-094 | `retrieve()` reranker passthrough | `_load_model`→None | `candidates[:rerank_top_k]` | graceful | — |
| KM-INT-095 | `retrieve()` no candidate | query tanpa match & store kosong | `[]` | kode | — |
| KM-INT-096 | `ingest_paths` 1 dokumen | file `.md` mini | kembalikan jumlah chunk > 0; baris tersimpan; `vector_dims(embedding)=1024` | `ingest_paths` | — |
| KM-INT-097 | `ingest_paths` PDF tanpa `pypdf` | monkeypatch ImportError | `""` + warning, tidak crash | `_load_text` | — |
| KM-INT-098 | `_store()` pilih backend | `VECTOR_BACKEND=pgvector` vs `qdrant` (monkeypatch) | modul store benar dipakai | `_store()` | — |

## 9. Agent node terisolasi (DB nyata + LLM stub)

Tiap node dipanggil `await <node>(state)` dengan state dirakit tangan; assert kunci balik +
`last_node` + `next_action`.

| ID | Node | Fokus asersi | Bug ref |
|---|---|---|---|
| KM-INT-100 | `intent_router_node` | LLM stub → `intent` valid; parse-fail → fallback `"tutoring"` | — |
| KM-INT-101 | `intent_router_node` mid-quiz | ada `quiz_session_id` + `quiz_questions` pending + `current_question_index` → paksa `intent="quiz"`, isi `student_answer` dari teks | bug 3 |
| KM-INT-102 | `intent_router_node` meta-command | teks "stop"/"ulangi"/"repeat" saat mid-quiz → **tidak** dipaksa quiz (`_is_meta_command`) | — |
| KM-INT-103 | `tutoring_node` | baca `user_input, current_concept_id, mastery_scores(.get cid,0.5), retrieved_docs`; balik `generated_response`, `next_action="accessibility_polish"`, append `HumanMessage`+`AIMessage` | bug 1 (import mati harus sudah dibersihkan) |
| KM-INT-104 | `problem_generator_node` | balik `quiz_session_id="quiz-..."`, `quiz_questions` (n sesuai `_decide_n_questions`), `current_question_index=0`, `quiz_attempts=[]`, `next_action="ask_question"` | — |
| KM-INT-105 | `quiz_node` (`quiz_ask`) | dari `quiz_questions[current_question_index]` → `quiz_question`, `generated_response` | — |
| KM-INT-106 | `mini_quiz_node` | dari `generated_response`+`current_concept_id` → `quiz_questions` len 1, `quiz_session_id="mini-..."`, `next_action="speak"` | #11 (node orphan — diuji langsung) |
| KM-INT-107 | `scoring_node` MCQ | `quiz_question.type="mcq"`, jawaban huruf → `quiz_attempts+1`, `quiz_score`, `cumulative_quiz_score` (mean), `next_action="analyze_quiz"` | — |
| KM-INT-108 | `scoring_node` spoken-semantic | `type="spoken"`, stub `embed_text` → cosine; `score=clip((sim-0.3)/0.6,0,1)` | — |
| KM-INT-109 | `scoring_node` rubric-LLM | `type="explain"`, stub `get_scoring_llm` kembalikan rubric JSON valid | — |
| KM-INT-110 | `quiz_analyzer_node` | dari `quiz_attempts`+`quiz_questions` → `misconceptions_detected`, `analytics_summary` (weak/strong/concept_averages/teacher_summary), `recommendations`, `next_action="update_student_model"` | — |
| KM-INT-111 | `quiz_analyzer_node` JSON fallback | stub LLM balikan non-JSON | cabang fallback deterministik dipakai, tidak crash | — |
| KM-INT-112 | `update_student_model_node` | lihat KM-INT-065 | #8 |
| KM-INT-113 | `analytics_node` | `student_id` valid → `StudentAggregator.summarise(window="month")` + `generate_student_spoken_summary`; `next_action="recommend"` | — |
| KM-INT-114 | `analytics_node` student_id non-UUID / `raw["error"]` | tangani anggun, `generated_response` informatif | — |
| KM-INT-115 | `recommendation_node` | dari `analytics_summary` → `recommendations: list[str]`, `analytics_summary.structured_recommendations`, `next_action="accessibility_polish"`; stub `get_recommendation_llm` **tanpa arg** | #8 |
| KM-INT-116 | `recommendation_node` fallback | stub LLM gagal → `_fallback(summary)` | — |
| KM-INT-117 | `accessibility_node` | `generated_response` dgn markdown+ref visual → `accessible_response` bersih; `next_action="speak"` | — |
| KM-INT-118 | `accessibility_node` simplify | `accessibility_flags.simplify_language=True` → `simplifier.simplify_with_llm(target_grade_level="7")` dipanggil (stub); tidak raise | #8 (getter `get_quiz_llm()` no-arg — target sudah benar di working tree) |
| KM-INT-119 | `accessibility_node` kosong | `generated_response=""` → `accessible_response=""`, tak crash | — |
| KM-INT-120 | `reflection_node` | stub LLM skor bagus → `next_action="accessibility_polish"`, `analytics_summary.last_reflection_score` | — |
| KM-INT-121 | `reflection_node` skor < 0.4 | → set `interrupt_reason`, mungkin rewrite `generated_response` | — |
| KM-INT-122 | `reflection_node` parse-fail | non-JSON → pass-through, tidak crash | — |
| KM-INT-123 | `stt_node` passthrough | `STT_ENABLED=false` → `transcribed_text = user_input`, `next_action="route_intent"` | — |
| KM-INT-124 | `tts_node` no-op | `TTS_ENABLED=false` → `audio_response_path=""`, `next_action="end"` | #19 (mkdir import-time aman) |

## 10. Graph utuh per intent (LLM stub, DB nyata, checkpointer Postgres test)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-140 | Path tutoring | `g.ainvoke(initial_state("s","<uuid>"), config)` dgn `intent` dipaksa tutoring (via stub router) | jalur `stt→intent_router→rag_retrieval→tutoring→reflection→accessibility→tts`; `accessible_response` non-kosong; `last_node="tts"` | struktur + node | — |
| KM-INT-141 | Path analytics | intent analytics | `analytics→recommendation→accessibility→tts`; `analytics_summary` terisi | struktur | — |
| KM-INT-142 | Path stop | intent stop | `intent_router→end_speak→tts→END` cepat | router | — |
| KM-INT-143 | Path quiz-start | intent quiz | `problem_generator→quiz_ask→tts`; `quiz_questions` terisi, `quiz_session_id` set | router | — |
| KM-INT-144 | Checkpointer setup | `AsyncPostgresSaver.from_conn_string(LANGGRAPH_DB_URI)` → `setup()` | tabel checkpoint terbuat; `g.ainvoke` menulis checkpoint per node | lifespan pattern | — |
| KM-INT-145 | Resume dari checkpoint | invoke sebagian (interrupt_after reflection) → lanjut dgn `thread_id` sama | state bertahan, lanjut ke `tts` | checkpointer | — |
| KM-INT-146 | `initial_state` cukup untuk semua node | invoke penuh | tidak ada `KeyError` di node manapun (state `total=False` + default lengkap) | `initial_state` | — |

## 11. Quiz multi-turn (jalur target — saat ini unreachable)

Seluruh grup `xfail(strict=True)` sampai #11/#5/#6/#1 diperbaiki. Ini **definition-of-done**
fitur kuis.

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-INT-150 | Start → soal pertama | invoke intent quiz utk concept `pecahan` | `quiz_session_id`, `quiz_questions` (≥3), `quiz_question` soal ke-0 | target | #11 |
| KM-INT-151 | Jawab → skor | utterance berikut = jawaban; graph masuk lewat `stt` → `intent_router` deteksi mid-quiz → **`scoring`** | `quiz_attempts` +1, `quiz_score` terisi | target: butuh cabang "quiz in progress" di `route_after_intent` + edge ke `scoring` | #11, bug 3 |
| KM-INT-152 | Skor → analyzer → route | `scoring→quiz_analyzer`; `route_after_scoring` pakai `settings.QUIZ_PASS_THRESHOLD` | lulus → `update_student_model`; gagal → `tutoring` | target | #11, #12 |
| KM-INT-153 | Soal berikutnya | `route_after_analyzer` idx+1 < len | kembali ke `quiz_ask` dgn soal ke-1 | target | #11 |
| KM-INT-154 | Soal habis → analytics → mastery persist | jawab semua | `analytics` dijalankan; `mastery_scores` di DB berubah sesuai attempt | target | #11 |

---

## Catatan implementasi

- **Fixture DB**: `db_engine` (session) memanggil `await init_db()` (env sudah `ENV=test`,
  `DB_NAME=kodmod_test`), lalu menjalankan DDL `create_test_db` sekali. `db_session`
  (function) membuka koneksi, `begin_nested()` (SAVEPOINT), yield session, rollback.
  Untuk node/graph yang memakai `async with async_session()` sendiri, gunakan pola
  "join external transaction" (SQLAlchemy) atau tandai test tersebut sebagai `serial`
  (tanpa xdist) dan bersihkan tabel di teardown.
- **`stub_embeddings`**: `hash(text) → RNG(seed) → np.array(1024)` dinormalisasi; ditanam ke
  `rag.embeddings.embed_text` dan referensi terikat di `rag.retriever`, `agents.scoring_agent`.
- **`stub_llms`**: `tests/_fakes/fake_chat.py` menyediakan `make_fake(role)` yang mengembalikan
  `GenericFakeChatModel` dengan antrean pesan valid per peran (JSON untuk intent_router /
  scoring rubric / quiz_analyzer / reflection; prosa untuk tutor / recommendation). Mendukung
  `.with_structured_output(Model)` dengan mengembalikan instance model contoh.
- **`classroom_enrollment` (#20)**: opsi perbaikan dicatat di `traceability.md` — tambah model
  ORM `ClassroomEnrollment` + sertakan di `create_test_db`, atau ubah `ClassroomAggregator`
  agar pakai relasi ORM. Test KM-INT-078/079 menjadi acuan.
