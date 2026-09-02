# Laporan Temuan Bug — KODMOD AI

Naskah untuk presentasi. Format tiap bug: **klaim/harapan → apa yang terjadi →
bukti kode → kenapa salah → dampak → cara demo → perbaikan**.

## Ringkasan eksekutif

| # | Bug | Lapisan | Dampak |
|---|---|---|---|
| 1 | `agents/tutoring_agent.py` meng-import simbol yang tidak ada (`StudentProfileTool`) | import-time | **Graf tidak bisa dibangun** → FastAPI tidak bisa start |
| 2 | `database/session.py` mengeksekusi string SQL mentah di SQLAlchemy 2.0 | runtime/DB | **`init_db()` selalu gagal** → tidak ada script/endpoint yang menyentuh DB bisa jalan |
| 3 | Loop inti kuis (jawab → nilai → update mastery) tidak dirangkai di `graphs/main_graph.py` | arsitektur/logika | **Fitur utama mati**: jawaban kuis tidak pernah dinilai; model mastery tidak pernah di-update lewat graf |

Ketiganya berlapis: (1) tidak bisa meng-import → (2) tidak bisa konek DB → (3)
meski keduanya diperbaiki, alur belajar adaptif tetap tidak jalan.

## Metodologi

Membaca sumber + menelusuri alur `StateGraph` node-per-node +
menjalankan komponen secara terpisah (env `hstone`, Python 3.11, Postgres
`pgvector/pgvector:pg16` via Docker).

## Prasyarat demo

Codebase pada cabang uji sudah memuat perbaikan kami. Untuk mereproduksi bug
**asli**, kembalikan file ke kondisi commit `HEAD`:

```bash
cd kodmod-ai            # direktori proyek nested
git stash              # revert 15 file yang kami ubah -> kode asli
# ... jalankan demo ...
git stash pop          # kembalikan perbaikan
```

`.env` untuk demo cukup 3 baris (hindari `CORS_ALLOW_ORIGINS`, lihat Lampiran L-16):

```
OPENAI_API_KEY=sk-...
DB_PORT=5433
DEBUG=false
```

Postgres: `docker compose -f docker/docker-compose.test.yml up -d`.

---

## Bug 1 — Graf tidak bisa dibangun: import simbol yang tidak ada

### Harapan
`build_kodmod_graph()` merakit `StateGraph` dari ~15 node. `api/main.py`
memanggilnya di lifespan; ini jantung sistem.

### Yang terjadi
Meng-import modul graf langsung melempar `ImportError`. Server tidak pernah
start.

### Bukti kode
`agents/tutoring_agent.py:29-35` (kondisi asli, `git show HEAD`):

```python
from graphs.state import KODMODState
from tools.llm_client import get_tutor_llm
from tools.rag_tool import RAGTool  # <- di-import, TIDAK dipakai
from tools.student_profile_tool import StudentProfileTool  # <- simbol TIDAK ADA
from prompts.loader import load_prompt
```

Isi `tools/student_profile_tool.py` — tidak ada `StudentProfileTool`:

```
$ git show HEAD:kodmod-ai/tools/student_profile_tool.py | grep -nE "^class |^def "
30:class StudentProfileInput(BaseModel):
54:def get_student_profile_tool() -> StructuredTool:
```

Rantai import: `graphs/main_graph.py:43` → `from agents.tutoring_agent import
tutoring_node` → memicu baris import di atas.

Cek `RAGTool` / `StudentProfileTool` tidak pernah dipakai di file itu:

```
$ grep -n "RAGTool\|StudentProfileTool" kodmod-ai/agents/tutoring_agent.py
33:from tools.rag_tool import RAGTool
34:from tools.student_profile_tool import StudentProfileTool
# (hanya baris import — nol pemakaian)
```

### Kenapa salah
Dua *dead import*. `StudentProfileTool` kemungkinan sisa refactor (nama berubah
jadi `get_student_profile_tool`). Python mengevaluasi import saat modul dimuat,
jadi symbol yang tidak ada = `ImportError` fatal, bukan warning.

### Dampak
- `build_kodmod_graph()` tidak bisa dipanggil sama sekali.
- `api/main.py` lifespan gagal → **FastAPI tidak bisa start**.
- Semua test yang menyentuh graf gagal saat collection.

### Demo

```bash
git stash
python -c "from graphs.main_graph import build_kodmod_graph"
```

Output:

```
ImportError: cannot import name 'StudentProfileTool' from 'tools.student_profile_tool'
(...\tools\student_profile_tool.py). Did you mean: 'StudentProfileInput'?
```

```bash
git stash pop
```

### Perbaikan
Hapus kedua baris import mati (tidak ada pemakaian yang perlu diganti):

```diff
-from tools.rag_tool import RAGTool
-from tools.student_profile_tool import StudentProfileTool
```

---

## Bug 2 — `init_db()` selalu melempar: string SQL mentah di SQLAlchemy 2.0

### Harapan
`init_db()` membuka engine async lalu "smoke test" koneksi (`SELECT 1`) supaya
gagal-cepat kalau Postgres tidak terjangkau. Dipanggil di lifespan
`api/main.py:47` dan di semua script (`seed_curriculum`, `ingest_documents`).

### Yang terjadi
Smoke test itu sendiri melempar `ObjectNotExecutableError` — bahkan ketika
Postgres sehat. `init_db()` tidak pernah selesai sukses.

### Bukti kode
`database/session.py:60-66` (kondisi asli):

```python
    # Smoke test connection — fail fast if DB is unreachable.
    try:
        async with _engine.connect() as conn:
            await conn.execute("SELECT 1")  # type: ignore[arg-type]
    except SQLAlchemyError as exc:
        logger.exception("Database connection failed at startup: %s", exc)
        raise
```

### Kenapa salah
SQLAlchemy 2.0 menghapus "implicit string execution". `Connection.execute()`
mensyaratkan objek *executable* (`sqlalchemy.text("SELECT 1")` atau konstruk
lain), bukan `str`. Komentar `# type: ignore[arg-type]` menunjukkan type checker
**sudah** menandai ini dan malah dibungkam, bukan diperbaiki. Catatan tambahan:
`except SQLAlchemyError` tidak menangkap `ObjectNotExecutableError` (turunannya
justru dari `exc.InvalidRequestError` → tetap `SQLAlchemyError`, tapi errornya
bukan soal "DB unreachable" seperti yang diasumsikan pesan log).

### Dampak
Meski Bug 1 diperbaiki: FastAPI tetap tidak bisa start, dan
`python -m scripts.seed_curriculum` / `ingest_documents` langsung crash. Tidak
ada jalur yang menyentuh DB yang berfungsi.

### Demo

```bash
git stash
docker compose -f docker/docker-compose.test.yml up -d      # Postgres SEHAT
python -m scripts.create_test_db
```

Output (potongan akhir):

```
  File ".../database/session.py", line 63, in init_db
    await conn.execute("SELECT 1")  # type: ignore[arg-type]
sqlalchemy.exc.ObjectNotExecutableError: Not an executable object: 'SELECT 1'
```

```bash
git stash pop
```

### Perbaikan

```diff
-from sqlalchemy.exc import SQLAlchemyError
+from sqlalchemy import text
+from sqlalchemy.exc import SQLAlchemyError
...
-            await conn.execute("SELECT 1")  # type: ignore[arg-type]
+            await conn.execute(text("SELECT 1"))
```

---

## Bug 3 — Loop inti kuis tidak terhubung di graf (fitur utama mati diam-diam)

### Harapan
Ini fitur unggulan produk. Alur yang dijanjikan (`docs/ARCHITECTURE.md`, komentar
di `main_graph.py`): murid menjawab soal → `scoring` menilai → `quiz_analyzer`
mendeteksi miskonsepsi → `update_student_model` memperbarui mastery di DB → kalau
gagal, balik ke `tutoring` untuk remediasi lalu kuis ulang.

Bahkan sudah ada mekanismenya di `intent_router`: kalau state menunjukkan kuis
sedang berjalan, ucapan berikutnya dipaksa jadi jawaban.

`agents/intent_router.py:78-92`:

```python
quiz_in_progress = bool(
    state.get("quiz_session_id")
    and state.get("quiz_questions")
    and state.get("current_question_index", 0) < len(state.get("quiz_questions", []))
)
if quiz_in_progress and not _is_meta_command(text):
    return {
        "intent": "quiz",
        "intent_confidence": 0.95,
        "student_answer": text,
        "next_action": "score_answer",  # <- sinyal untuk router
        "last_node": "intent_router",
    }
```

### Yang terjadi
`route_after_intent` **tidak punya** cabang untuk "kuis sedang berjalan". Untuk
`intent == "quiz"` ia selalu mengembalikan `"problem_generator"` — yang
**membuat kuis baru dari nol** dan menimpa `quiz_session_id` / `quiz_questions` /
`quiz_attempts`. `scoring`, `quiz_analyzer`, `update_student_model` **tidak pernah
tereksekusi** lewat graf.

### Bukti kode

**(a) Router mengabaikan `next_action` dan mengirim jawaban ke pembuatan soal.**
`graphs/main_graph.py:66-85`:

```python
def route_after_intent(state: KODMODState) -> str:
    intent = state.get("intent", "unknown")
    if intent == "tutoring":
        return "rag_retrieval"
    if intent == "quiz":
        return "problem_generator"  # <- selalu
    if intent == "exercise_request":
        return "problem_generator"
    if intent == "analytics":
        return "analytics"
    if intent in ("repeat", "clarification"):
        return "tutoring"
    if intent == "stop":
        return "end_speak"
    return "tutoring"
```

Peta cabang dari `intent_router` (`main_graph.py:155-165`) — **tidak ada
`"scoring"`**:

```python
graph.add_conditional_edges(
    "intent_router",
    route_after_intent,
    {
        "rag_retrieval": "rag_retrieval",
        "problem_generator": "problem_generator",
        "analytics": "analytics",
        "tutoring": "tutoring",
        "end_speak": "tts",
    },
)
```

**(b) `scoring` tak terjangkau dari `START`.** Satu-satunya edge menuju `scoring`
adalah `mini_quiz → scoring` (`main_graph.py:174`), tapi **tidak ada edge yang
masuk ke `mini_quiz`**:

```
$ grep -n 'add_edge(' kodmod-ai/graphs/main_graph.py | grep -E '"mini_quiz"|"scoring"'
174:    graph.add_edge("mini_quiz", "scoring")
182:    graph.add_edge("scoring", "quiz_analyzer")
# tidak ada  add_edge(<apa pun>, "mini_quiz")
```

**(c) Sinyal `next_action="score_answer"` tidak pernah dibaca.**

```
$ grep -rn "score_answer" --include=*.py kodmod-ai/ | grep -v tests
kodmod-ai/agents/intent_router.py:91:            "next_action": "score_answer",   # ditulis
kodmod-ai/graphs/state.py:55:    "score_answer",                                  # deklarasi tipe
# nol pembaca
```

**(d) Komentar yang menyesatkan** — `main_graph.py:179-180` menyatakan kebalikan
dari perilaku kode:

```python
    # NOTE: when student answers, a NEW graph invocation re-enters at "stt"
    # and the intent router recognizes "quiz_in_progress" → routes to scoring.
```

**(e) Nama router tidak cocok dengan titik pasangnya** (`main_graph.py:183-198`):
`route_after_scoring` dipasang ke node `quiz_analyzer` (bukan `scoring`), dan
`route_after_analyzer` dipasang ke `update_student_model`.

### Kenapa salah
Node `scoring` / `quiz_analyzer` / `update_student_model` didaftarkan sebagai
node tapi tidak pernah masuk ke jalur eksekusi manapun dari `START`. LangGraph
tidak error untuk node yatim — ia diam saja. Jadi seluruh klaster penilaian +
persistensi mastery + loop remediasi adalah **dead code dari sudut pandang graf**.

### Dampak
- Murid menjawab soal → graf **membuat kuis baru** alih-alih menilai (di CLI kami
  hal ini terlihat sebagai "Soal pertama" berulang tiap giliran).
- `scoring_node`, `quiz_analyzer_node`, `update_student_model_node` tidak pernah
  jalan lewat pemakaian normal.
- Tabel `mastery_scores` **tidak pernah di-update** oleh alur percakapan → premis
  "tutor adaptif berbasis BKT" tidak terpenuhi.
- Loop remediasi (skor < 0.6 → jelaskan ulang → kuis lagi) tidak pernah aktif.

### Demo

**Demo 1 — keputusan routing (tanpa DB/LLM):**

```bash
python -c "
from graphs.main_graph import route_after_intent
st = {'intent':'quiz','quiz_session_id':'q1',
      'quiz_questions':[{'question_id':'a'},{'question_id':'b'}],
      'current_question_index':0,'student_answer':'B','next_action':'score_answer'}
print('hasil route:', route_after_intent(st))
"
```

Output:

```
hasil route: problem_generator      # <- jawaban murid dikirim ke PEMBUAT SOAL, bukan 'scoring'
```

**Demo 2 — di CLI:** `scripts/chat_cli.py` terpaksa memakai perintah `/answer`
yang memanggil `scoring_node` **langsung** (bukan lewat graf). Komentar di
`do_answer` / notebook `text_mode_smoke.ipynb` §"Fitur 6" menyatakan alasannya:
*"scoring_node tak terjangkau dari START ... jadi kita panggil koroutin node
langsung"*. Perancah ini sendiri adalah bukti bug-nya.

Bandingkan: kirim jawaban sebagai teks bebas yang **melewati graf** → tiap
giliran menghasilkan set soal baru (`quiz_session_id` berubah, `quiz_attempts`
tetap kosong, `quiz_score` tidak pernah muncul).

### Perbaikan (garis besar, belum kami terapkan)
1. `route_after_intent`: tambah cabang paling awal —
   `if state.get("quiz_session_id") and state.get("current_question_index",0) < len(state.get("quiz_questions",[])): return "scoring"`,
   dan daftarkan `"scoring": "scoring"` di peta `add_conditional_edges`.
2. Sambungkan hasil `scoring`: `scoring → quiz_analyzer` sudah ada; pastikan
   `route_after_scoring` dipasang ke node yang benar.
3. Pakai checkpointer Postgres + `thread_id` tetap supaya state kuis bertahan
   antar `ainvoke` (tanpa itu, giliran ke-2 mulai dari state kosong).
4. Hapus/ganti komentar menyesatkan di `main_graph.py:179-180`.

---

## Lampiran — temuan lain (ringkas)

Semua sudah kami perbaiki di cabang uji kecuali yang bertanda **(terbuka)**.

| # | Lokasi | Masalah |
|---|---|---|
| L-1 | `agents/analytics_agent.py:45-46` | `StudentAggregator(student_id=…).compute()/.persist()` — kelas hanya punya `.summarise()`; `intent=analytics` langsung `TypeError` |
| L-2 | `tools/rag_tool.py:56-57` | `from rag.stores.pgvector_store import PgVectorStore` — kelas tidak ada (modul isinya fungsi); `RAGTool()` di `problem_generator` → `ImportError` |
| L-3 | `rag/retriever.py:53` & `rag/ingestion.py:47-51` | `str` dioper ke `embed_text(Sequence[str])` → di-`list()` jadi per-karakter → retrieval & ingestion RAG **tidak pernah berfungsi**; lanjut `TypeError` di `_vec_literal` |
| L-4 | `rag/embeddings.py:36` | jalur OpenAI hardcode `text-embedding-3-large` (3072-dim), tapi kolom `curriculum_chunks.embedding` = `vector(1024)` & index HNSW pgvector maks 2000-dim → insert/query gagal |
| L-5 | `database/schema.sql` vs `database/models.py` | dua skema **tidak kompatibel** untuk tabel yang sama (`concepts.id VARCHAR(64)` vs `UUID`; `mastery_scores.score/last_practiced` vs `mastery/last_seen`; `students.display_name` vs `full_name`). `analytics/student_model.py` menyasar skema-1, sisanya skema-2. Docstring keduanya saling klaim "source of truth" |
| L-6 | `database/models.py` (docstring) | menyebut model `CurriculumChunk` tapi tidak didefinisikan → `Base.metadata.create_all` tidak membuat tabel RAG |
| L-7 | `voice/tts.py:43` | `OUTPUT_DIR.mkdir(...)` saat import, tanpa `try/except`, default `/var/lib/kodmod/audio` → `PermissionError` saat import di Windows / env terbatas (`config/settings.py` menjaga pola yang sama, file ini tidak) |
| L-8 | `api/routes/quiz.py`, `api/routes/voice.py` | `state["learning_profile"] = student.profile` — ORM `Student` tidak punya atribut `profile` → `AttributeError` di `/quiz/start`, `/voice/text`, `/voice/chat` **(terbuka)** |
| L-9 | `api/routes/quiz.py:96-98` | `await StudentModel.load(id).mastery_scores()` — meng-chain atribut dari coroutine → `AttributeError` **(terbuka)** |
| L-10 | `api/routes/exercise.py:41`, `tools/quiz_generator_tool.py:46` | import `generate_questions_for_student` dari `agents.problem_generator` — fungsi tidak ada → `/exercise/generate` mati **(terbuka)** |
| L-11 | `agents/accessibility_agent.py:87` | memanggil `simplify_with_llm(..., target_grade=…)`; parameter aslinya `target_grade_level` → `TypeError` saat jalur simplify aktif |
| L-12 | `accessibility/simplifier.py:61` | `get_quiz_llm(temperature=0.2)` — getter ber-`@lru_cache` tidak menerima argumen → `TypeError` |
| L-13 | `accessibility/narration.py:122` | `get_tutor_llm(temperature=0.2)` — sama; `describe_image` (narasi gambar) selalu gagal **(terbuka, di luar mode teks)** |
| L-14 | `tests/integration/test_graph_wiring.py` | `build_kodmod_graph(checkpointer=None)` tidak di-`await` (padahal `async`); `initial_state(student_id=…)` tanpa `session_id` wajib → satu-satunya test graf justru rusak **(terbuka)** |
| L-15 | `tests/unit/test_student_model.py` | memanggil `model.update(concept_id=…, correct=True, score=1.0)`; signature asli `update(concept_id, attempt_score, confidence)` → 6 test `TypeError` **(terbuka)** |
| L-16 | `config/settings.py` | `CORS_ALLOW_ORIGINS: List[str]` + nilai `.env` `*` → pydantic-settings meng-`json.loads("*")` sebelum validator → `SettingsError` hanya karena ada file `.env` |

## Catatan

- Perbaikan kami ada di working tree (belum di-commit). `git diff` menampilkan
  14 file yang diubah; ringkasannya di `docs/TEXT_MODE_TESTING.md` §A.1.
- Bug 3, L-5, L-8..L-10, L-13..L-15 belum diperbaiki (butuh keputusan desain /
  di luar cakupan uji mode teks).
