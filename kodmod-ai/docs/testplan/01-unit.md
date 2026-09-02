# Stage 1 — Unit Test (logika murni)

**Tujuan.** Mengunci fondasi semantik: matematika BKT, chunking RAG, routing graph, helper
aksesibilitas, parsing perintah suara, aturan insight, helper JWT. Semua **tanpa I/O** —
tanpa DB, Redis, LLM, jaringan, filesystem.

**Sifat gate.** Blok. Dijalankan paling sering saat perbaikan (cepat, < 30 s).

**Framework.** `pytest` murni + `pytest-randomly`. Parametrize agresif. `hypothesis`
opsional untuk properti numerik (batas [0,1], monotonisitas).

**Entry.** Stage 0 hijau. **Exit.** `pytest -m "unit and not known_bug"` semua hijau;
coverage modul-modul di bawah ≥ 90 % baris.

**Lokasi.** `tests/unit/` (konsolidasi 4 file lama + file baru per area).

**Marker.** `unit`. Perilaku target dari bug yang belum di-fix → asersi biasa (MERAH) +
`@pytest.mark.known_bug("#n")` — **bukan** `xfail`. Lihat README §6.1.

---

## 1. RAG chunking — `rag/chunking.py`  *(sebagian sudah ada di `test_chunking.py`)*

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-010 | Teks sederhana ≥ 1 chunk | `chunk_document("halo dunia", source="s")` | `len >= 1`, `chunk.source == "s"` | fungsi | — |
| KM-UNIT-011 | Hormati batas section | teks dgn `# Bab 1` / `# Bab 2`, `target_tokens=20` | tiap `Chunk.section_title` sesuai heading induk | `_split_on_headings` | — |
| KM-UNIT-012 | Teks panjang → banyak chunk | teks ~400 token, `target_tokens=80, max_tokens=120` | `len(chunks) >= 3`, tak ada chunk > `max_tokens` (`_approx_tokens`) | fungsi | — |
| KM-UNIT-013 | Ekstraksi referensi gambar | teks memuat "lihat Gambar 3.2" & "Tabel 4" | `chunk.referenced_figures` memuat keduanya (via `_FIGURE_RE`) | regex | — |
| KM-UNIT-014 | Overlap kalimat | `overlap_sentences=1` | kalimat terakhir chunk N muncul sebagai pembuka chunk N+1 | fungsi | — |
| KM-UNIT-015 | Edge `flush()` gabung kalimat | input yang memicu cabang `" ".join(extra_sentences or [] + buf)` | tidak ada kalimat hilang/dobel; urutan utuh | inspeksi presedensi `[] + buf` | *(potensi bug — dokumentasikan bila salah)* |
| KM-UNIT-016 | Input kosong / whitespace | `chunk_document("", source="s")`, `"   \n"` | `[]` atau 1 chunk kosong sesuai kontrak; tidak `IndexError` | fungsi | — |
| KM-UNIT-017 | `chunks_to_payloads` | konversi list `Chunk` | tiap payload punya `text, source, section_title, chunk_index, referenced_figures` | fungsi | — |
| KM-UNIT-018 | `_approx_tokens` | `"a"*400` | `== 100` (`len//4`, min 1) | fungsi | — |

## 2. BKT mastery — `analytics/student_model.py` (bagian murni)  *(tulis ulang `test_student_model.py` — API lama usang, #18)*

Konstanta: `LEARNING_RATE = 0.25`, `DAILY_DECAY = 0.005`.
Signature nyata: `update(concept_id, attempt_score, confidence=0.9)`, `apply_decay()` **tanpa arg**,
`weak_concepts(n=3) -> list[str]`, `strong_concepts(n=3) -> list[str]`, `overall_mastery() -> float`,
`mastery_scores()` **async**.

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-020 | Jawaban benar menaikkan mastery | `m.update("c", 1.0)` dari prev 0.5 | `scores["c"] == 0.5 + (1.0-0.5)*0.25*0.9 == 0.6125` | rumus `delta` | #18 |
| KM-UNIT-021 | Jawaban salah menurunkan/meredam | `m.update("c", 0.0)` dari prev 0.5 | `scores["c"] == 0.5 + (0.0-0.5)*0.25*0.9 == 0.3875` | rumus | #18 |
| KM-UNIT-022 | Terikat [0,1] | 50× `update("c", 1.0)` lalu 50× `update("c", 0.0)` | selalu `0.0 <= score <= 1.0` | `max(0,min(1,...))` | #18 |
| KM-UNIT-023 | Confidence naik +0.05 dibatasi 1.0 | `update` berulang | `_confidence["c"]` naik 0.05/step, tak lewat 1.0 | fungsi | #18 |
| KM-UNIT-024 | `n_attempts` bertambah | 3× `update` | `_attempts["c"] == 3` | fungsi | #18 |
| KM-UNIT-025 | `apply_decay()` tanpa arg | set `_last_practiced["c"] = now-30d`, `apply_decay()` | `score -= 0.005*30 == 0.15` (floor 0.0) | rumus decay | #18 |
| KM-UNIT-026 | Decay 0 hari | `_last_practiced = now` | skor tak berubah | `max(0,(now-last).days)` | #18 |
| KM-UNIT-027 | `weak_concepts` urut naik, kunci saja | 3 konsep skor beda | kembalikan `list[str]` skor terendah dulu, `len == n` | fungsi | #18 |
| KM-UNIT-028 | `strong_concepts` urut turun | idem | `list[str]` skor tertinggi dulu | fungsi | #18 |
| KM-UNIT-029 | `overall_mastery` = rata-rata | 3 skor | mean; `0.0` bila kosong | fungsi | #18 |
| KM-UNIT-030 | `mastery_scores()` async & salinan | `await m.mastery_scores()` | `dict` sama isi, bukan referensi internal | fungsi | #18 |

## 3. Scoring helpers — `agents/scoring_agent.py` (murni)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-040 | `_score_mcq` huruf benar | expected `"B"`, jawaban `"b"` | `(1.0, <feedback benar>)` | fungsi | — |
| KM-UNIT-041 | `_score_mcq` huruf salah | expected `"B"`, jawaban `"C"` | `(0.0, <feedback salah>)` | fungsi | — |
| KM-UNIT-042 | `_score_mcq` jawaban teks penuh cocok opsi | jawaban = teks opsi B lengkap | skor `1.0` | fungsi | — |
| KM-UNIT-043 | `_score_mcq` opsi kosong | `options=[]` | tidak `IndexError`; skor `0.0` + feedback aman | fungsi | — |
| KM-UNIT-044 | `_build_attempt` bentuk | panggil dgn field lengkap | `QuizAttempt` TypedDict valid (`question_id, student_answer, score, is_correct, confidence`) | `graphs/state.py` | — |
| KM-UNIT-045 | `is_correct` ambang 0.6 | skor 0.59 vs 0.60 | `False` vs `True` | konstanta di modul | — |
| KM-UNIT-046 | `_emit` kumulatif = mean | 3 attempt skor `[1,0,0.5]` | `cumulative_quiz_score == 0.5` | fungsi | — |
| KM-UNIT-047 | `_empty_attempt` | panggil | attempt skor 0, `is_correct False`, tidak crash downstream | fungsi | — |

## 4. Problem generator helpers — `agents/problem_generator.py` (murni)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-050 | `_decide_n_questions` fatigued/frustrated | state `emotional_state="frustrated"` | `3` | fungsi | — |
| KM-UNIT-051 | `_decide_n_questions` motivated | `"motivated"` | `7` | fungsi | — |
| KM-UNIT-052 | `_decide_n_questions` default | `"neutral"` | `5` | fungsi | — |
| KM-UNIT-053 | `_infer_concept` mastery terlemah | `mastery_scores={"a":0.9,"b":0.2}` | `"b"` | fungsi | — |
| KM-UNIT-054 | `_infer_concept` kosong | `mastery_scores={}` , tanpa `current_concept_id` | `"general"` | fungsi | — |
| KM-UNIT-055 | `_fallback_question` valid | `_fallback_question("pecahan","easy")` | `QuizQuestion` TypedDict lengkap (`question_id, text, type, concept_id, difficulty`) | `graphs/state.py` | — |

## 5. Router graph (fungsi murni) — `graphs/main_graph.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-060 | `route_after_intent` tutoring | `intent="tutoring"` | `"rag_retrieval"` | kode router | — |
| KM-UNIT-061 | `route_after_intent` quiz / exercise_request | masing-masing | `"problem_generator"` | kode | — |
| KM-UNIT-062 | `route_after_intent` analytics / repeat / clarification / stop / default | tabel parametrize | `analytics` / `tutoring` / `tutoring` / `end_speak` / `tutoring` | kode | — |
| KM-UNIT-063 | `route_after_scoring` pakai `settings.QUIZ_PASS_THRESHOLD` | `quiz_score=0.6`, `settings.QUIZ_PASS_THRESHOLD=0.7` (monkeypatch) | `"tutoring"` (bukan `update_student_model`) | spec: harus baca settings, bukan hardcode `0.6` | #12 — **FIXED 2026-09-02**, asersi biasa |
| KM-UNIT-064 | `route_after_scoring` lulus | `quiz_score >= threshold` | `"update_student_model"` | kode | — |
| KM-UNIT-065 | `route_after_analyzer` masih ada soal | `current_question_index+1 < len(quiz_questions)` | `"quiz_ask"` | kode | — |
| KM-UNIT-066 | `route_after_analyzer` soal habis | idem sebaliknya | `"analytics"` | kode | — |
| KM-UNIT-067 | Router robust terhadap state parsial | state tanpa `quiz_questions` | tidak `KeyError` (pakai `.get`) | kode | — |

## 6. State — `graphs/state.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-070 | `initial_state` isi semua field | `initial_state("s1", student_id=<uuid>)` | semua kunci `KODMODState` terisi; `intent="unknown"`, `next_action="route_intent"`, `current_difficulty="medium"`, `detected_language="id"`, `emotional_state="neutral"`, `last_node="entry"` | fungsi | #18 |
| KM-UNIT-071 | `session_id` wajib | `initial_state(student_id=...)` tanpa `session_id` | `TypeError` (positional wajib) | signature | #18 |
| KM-UNIT-072 | `request_id`/`trace_id` unik & `started_at` ISO | 2× panggil | id berbeda; `started_at` parseable ISO-8601 UTC | fungsi | — |
| KM-UNIT-073 | `messages` reducer siap | field `messages` = list kosong, tipe cocok `add_messages` | list | anotasi | — |

## 7. Aksesibilitas — helper murni  *(sebagian sudah ada di `test_accessibility_narration.py`)*

### `agents/accessibility_agent.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-080 | `_strip_markdown` | `"**tebal** `kode` [x](u) # H"` | tanpa `**`, backtick, `#`; `[x](u)`→`x` | regex `_MARKDOWN` | — |
| KM-UNIT-081 | `_replace_visual_refs` ID | `"lihat gambar di atas"` | jadi `"perhatikan baik-baik"` (atau frasa non-visual sesuai kode) | regex `_VISUAL_REFS` | — |
| KM-UNIT-082 | `_replace_visual_refs` EN | `"as shown in the figure below"` | dihilangkan/diganti | regex | — |
| KM-UNIT-083 | `_split_long_sentences` | kalimat 150 char dgn koma di idx 60 | dipecah di koma (idx>40) | fungsi (`_LONG_SENTENCE` ≥120) | — |
| KM-UNIT-084 | `_split_long_sentences` tanpa koma | 150 char tanpa koma | tetap utuh (tidak ada titik potong aman) | fungsi | — |
| KM-UNIT-085 | `_normalize_numbers` | `"nilai 3.2 dan 10.75"` | `"3 titik 2"`, `"10 titik 75"` | regex `\b(\d+)\.(\d+)\b` | — |
| KM-UNIT-086 | `_add_ssml_breaks` | `"Benar? Bagus! Lalu. Selanjutnya."` | `<break time="400ms"/>` setelah `?`/`!`; `<break time="250ms"/>` setelah `. ` sebelum kapital | fungsi | — |
| KM-UNIT-087 | `_should_simplify` panjang | teks 1300 char | `True` | `len>1200 or count(",")>30` | — |
| KM-UNIT-088 | `_should_simplify` koma banyak | 31 koma, < 1200 char | `True` | fungsi | — |
| KM-UNIT-089 | `_should_simplify` normal | 200 char, 5 koma | `False` | fungsi | — |
| KM-UNIT-090 | Pipeline fast-path order | input campur markdown+visual+angka+kalimat panjang | urutan transform: strip_markdown → replace_visual → narration → split_long → normalize_numbers → add_ssml | kode `accessibility_node` | — |

### `accessibility/narration.py` — `describe_visuals_in_text`  *(sudah ada, pertahankan + perluas)*

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-091 | Ganti "lihat gambar 3.2" | teks referensi gambar | referensi hilang/diganti | pola | — |
| KM-UNIT-092 | Ganti warna → penanda | `"garis berwarna merah"` | `"garis penanda"` | pola | — |
| KM-UNIT-093 | Idempoten | teks tanpa ref visual | tak berubah | fungsi | — |
| KM-UNIT-094 | Input kosong / None | `""`→`""`, `None`→`None` | sesuai | fungsi | — |
| KM-UNIT-095 | Collapse whitespace | setelah substitusi | tidak ada spasi ganda; tidak ada spasi sebelum tanda baca | fungsi | — |
| KM-UNIT-096 | `context_descriptions` | `{"gambar_4.1":"segitiga"}` | id gambar diganti deskripsi | fungsi | — |

### `accessibility/voice_commands.py`  *(sudah ada, pertahankan)*

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-100 | `detect_command` positif | parametrize 13 ucapan (repeat/stop/slower/faster/next/back/help/start_quiz; ID+EN+kapital) | `VoiceCommand.name` sesuai | `_COMMANDS` regex | — |
| KM-UNIT-101 | `detect_command` negatif | 4 ucapan biasa | `None` | fungsi | — |
| KM-UNIT-102 | `help_text` lokalisasi | `help_text("id")` / `("en")` | string berbeda, non-kosong | konstanta | — |
| KM-UNIT-103 | `is_terminal` | `stop`/`help`/`repeat` vs lainnya | `True` vs `False` | `.is_terminal()` | — |
| KM-UNIT-104 | `detect_command` kosong/whitespace | `""`, `"  "` | `None` | fungsi | — |

## 8. Insights (rule-based) — `analytics/insights.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-110 | `_pct` | `0.42` | `"42 persen"` | fungsi | — |
| KM-UNIT-111 | `_format_concept_list` | 5 item, `n=3` | 3 nama, dipisah sesuai format | fungsi | — |
| KM-UNIT-112 | `_window_start` today/week/month/all | parametrize | midnight / -7d / -30d / `None` | fungsi | — |
| KM-UNIT-113 | `generate_student_spoken_summary` error | `{"error":"student_not_found"}` | kalimat "tidak ditemukan" (ID), bukan exception | fungsi | — |
| KM-UNIT-114 | `...` 0 sesi | `{"n_sessions":0,...}` | kalimat "belum ada sesi" | fungsi | — |
| KM-UNIT-115 | `...` tier akurasi ≥0.8 / ≥0.6 / >0 | 3 dataset | frasa pujian sesuai tier | fungsi | — |
| KM-UNIT-116 | `generate_teacher_summary` alert akurasi rendah | `n_attempts>=3, accuracy<0.5` | ada alert `severity="warning"` | aturan | — |
| KM-UNIT-117 | `...` engagement rendah | `engagement<0.2, n_sessions<=1` | alert warning | aturan | — |
| KM-UNIT-118 | `...` miskonsepsi terbuka | `open_misconceptions>0` | alert info | aturan | — |
| KM-UNIT-119 | `...` mastery tinggi | `overall_mastery>=0.85` | alert success | aturan | — |
| KM-UNIT-120 | `generate_classroom_alerts` konsep lemah | `class_weak_concepts[0].avg_mastery<0.5` | alert warning | aturan | — |
| KM-UNIT-121 | `...` engagement kelas rendah | `avg_engagement_index<0.3` | alert info | aturan | — |
| KM-UNIT-122 | `generate_insights(use_llm=False)` | dataset normal | `{"spoken","structured"}` tanpa panggil LLM | fungsi | — |
| KM-UNIT-123 | `generate_insights(use_llm=True)` | spy getter | getter dipanggil **tanpa arg** (`get_recommendation_llm()`) | signature getter | #8 — **FIXED 2026-09-02**, asersi biasa |

## 9. LLM client — `tools/llm_client.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-130 | Getter kembalikan model | monkeypatch `_FACTORIES` → fake; `get_tutor_llm()` | objek punya `ainvoke`/`astream` | kontrak LangChain Runnable | — |
| KM-UNIT-131 | Provider switch | set `KODMOD_LLM_PROVIDER=openai`, `get_router_llm.cache_clear()`, panggil | factory `openai` dipakai | `_provider()` | — |
| KM-UNIT-132 | `get_recommendation_llm() is get_quiz_llm()` | bandingkan | objek/identitas sama | kode | — |
| KM-UNIT-133 | Getter menolak argumen | `get_tutor_llm(temperature=0.2)` | `TypeError` | signature (`@lru_cache` tanpa param) — dipakai salah di `narration.py` | #8 |
| KM-UNIT-134 | `vllm` pakai `api_key="EMPTY"` & base_url env | set provider `vllm`, `VLLM_BASE_URL` | factory pakai nilai itu | `_vllm` | — |

## 10. JWT helper — `api/dependencies.py` (fungsi murni `_decode_jwt`, + helper `make_token` baru di `tests/_fakes/jwt.py`)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-140 | Encode→decode round-trip | token `{sub,role:"student"}` dgn `settings.JWT_SECRET` | `_decode_jwt` kembalikan payload sama | PyJWT | — |
| KM-UNIT-141 | Token kedaluwarsa | `exp` di masa lalu | `HTTPException(401,"Token expired")` | `ExpiredSignatureError` | — |
| KM-UNIT-142 | Secret salah | sign dgn secret lain | `HTTPException(401,"Invalid token...")` | `PyJWTError` | — |
| KM-UNIT-143 | `alg=none` | token unsigned `alg=none` | ditolak 401 | `algorithms=[settings.JWT_ALG]` | — |

## 11. Reranker & pgvector literal (murni)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-UNIT-150 | `rerank` passthrough saat model None | monkeypatch `rag.reranker._load_model` → `None`; `await rerank("q", docs, top_k=2)` | `docs[:2]` tanpa `rerank_score`, urutan asli | kode graceful-degrade | — |
| KM-UNIT-151 | `_vec_literal` format | `_vec_literal([0.123456789, 1.0])` | `"[0.1234568,1.0000000]"` (7 dp) | fungsi | — |
| KM-UNIT-152 | `embed_text([])` | `await embed_text([])` | `[]` tanpa muat model | jalur kosong murni | — |

---

## Catatan implementasi

- File baru: `tests/unit/test_bkt.py` (ganti `test_student_model.py`), `test_scoring_helpers.py`,
  `test_problem_generator_helpers.py`, `test_routers.py`, `test_state.py`,
  `test_accessibility_helpers.py`, `test_insights.py`, `test_llm_client.py`, `test_jwt.py`,
  `test_rerank_pure.py`. Pertahankan `test_chunking.py`, `test_accessibility_narration.py`,
  `test_voice_commands.py` (perluas).
- Hindari import berat: unit test **tidak** boleh meng-import `api.main`, `graphs.main_graph`
  penuh (yang menarik semua node). Router diuji dengan mengimpor fungsi `route_after_*`
  langsung dari `graphs.main_graph` — jika itu memicu import node berat, ekstraksi router ke
  modul terpisah dicatat sebagai rekomendasi refactor kecil di `traceability.md`.
- `stub_llms`/`stub_embeddings` autouse tetap aktif (defensif) walau stage ini idealnya tak
  menyentuh keduanya.
