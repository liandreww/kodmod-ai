# Uji Coba Mode Teks (TTS/STT nonaktif)

Panduan menjalankan KODMOD AI untuk **uji coba** dengan input & output berupa teks —
tanpa speech-to-text dan text-to-speech, memakai **OpenAI** untuk LLM & embedding.

Semua perintah dijalankan dari direktori proyek nested: `kodmod-ai/`.

---

## A. Runbook setup

### A.1 Patch kode yang sudah diterapkan

| File | Alasan |
|---|---|
| `config/settings.py` | `TTS_ENABLED` / `STT_ENABLED` (default `True`). |
| `voice/tts.py` | `mkdir` saat import dibungkus `try/except`; `tts_node` langsung `return` bila `TTS_ENABLED=false`. |
| `voice/stt.py` | `stt_node` passthrough bila `STT_ENABLED=false`. |
| `database/session.py` | `conn.execute("SELECT 1")` → `conn.execute(text("SELECT 1"))` (SQLAlchemy 2.0). Tanpa ini `init_db()` selalu gagal. |
| `rag/retriever.py` | `embed_text(query)` → `(await embed_text([query]))[0]` (kontraknya `Sequence[str]`). |
| `rag/ingestion.py` | `_embed_batch` tidak lagi mengoper `str` per-karakter ke `embed_text`. |
| `rag/embeddings.py` | backend `openai` → `text-embedding-3-small` dengan `dimensions=1024` (cocok kolom `vector(1024)` + limit index ANN pgvector 2000 dim). Bisa dioverride via `KODMOD_EMBED_MODEL` / `KODMOD_EMBED_DIM`. |
| `rag/stores/pgvector_store.py` | Tambah kelas `PgVectorStore` (dipakai `RAGTool` — sebelumnya `ImportError`). Filter `concept_id` di SQL di-`CAST(... AS uuid)`. |
| `tools/llm_client.py` | Model OpenAI keempat peran → `gpt-5.6-luna`. |
| `agents/analytics_agent.py` | `StudentAggregator(student_id=...).compute()/.persist()` (tidak ada) → `StudentAggregator().summarise(student_id=..., window="month")`; pemetaan key disesuaikan; ringkasan lisan pakai `generate_student_spoken_summary`. |
| `analytics/student_model.py` | Kolom raw SQL diselaraskan dengan ORM `MasteryScore`: `score`→`mastery`, `last_practiced`→`last_seen`; `INSERT` menyertakan `id = gen_random_uuid()`; `student_id`/`concept_id` di-`CAST(... AS uuid)`. |
| `agents/accessibility_agent.py` | `simplify_with_llm(..., target_grade=...)` → `target_grade_level=...`. |
| `accessibility/simplifier.py` | `get_quiz_llm(temperature=0.2)` → `get_quiz_llm()` (getter tak menerima argumen). |

> ⚠️ **`gpt-5.6-luna` belum bisa diverifikasi** sebagai id model OpenAI yang valid.
> Kalau API menolak (`invalid model` / 404), ganti keempat entri `"openai"` di
> `tools/llm_client.py` ke `gpt-4.1-mini` atau `gpt-4o-mini`.

### A.2 Install

```bash
cd kodmod-ai
pip install -e ".[dev]"
```

Ini menarik `torch`/`sentence-transformers`/`faster-whisper` (besar, ~2–5 GB) sebagai
dependensi transitif meski di mode ini tidak dipakai runtime. `HF_HUB_OFFLINE=1` +
`TRANSFORMERS_OFFLINE=1` (di-set notebook) mencegah unduhan bobot model apa pun.

### A.3 Postgres (Docker)

`database/schema.sql` yang di-autoload `docker-compose.yml` **tidak sinkron** dengan
`database/models.py` dan kode store. Gunakan compose khusus tanpa autoload:

```bash
docker compose -f docker/docker-compose.test.yml up -d
docker compose -f docker/docker-compose.test.yml ps      # tunggu "healthy"
# reset bersih: docker compose -f docker/docker-compose.test.yml down -v
```

Container ini memetakan **host port 5433** (bukan 5432) supaya tidak bentrok
dengan Postgres lain yang mungkin sudah jalan di mesin. Karena itu `.env` harus
memuat `DB_PORT=5433`.

Alternatif tanpa compose:

```bash
docker run -d --name kodmod-pg -p 5433:5432 \
  -e POSTGRES_USER=kodmod -e POSTGRES_PASSWORD=kodmod -e POSTGRES_DB=kodmod \
  pgvector/pgvector:pg16
```

Redis **tidak diperlukan** — tidak ada node graf yang menyentuhnya.

> **`password authentication failed for user "kodmod"`** = ada Postgres LAIN di
> port itu (instalasi lokal Windows, atau container `kodmod-postgres` lama dari
> `docker-compose.yml`). Cek: `docker ps | findstr postgres` dan
> `netstat -ano | findstr :5432`. Pakai port 5433 seperti di atas untuk
> menghindarinya, atau hentikan Postgres yang lama.

### A.4 Buat tabel + seed

```bash
python -m scripts.create_test_db     # create_all dari ORM + tabel curriculum_chunks
python -m scripts.seed_curriculum    # subjects/concepts/lessons contoh (idempoten)
```

Concept slug hasil seed: `pecahan`, `persamaan-linear`, `bangun-datar`,
`fotosintesis`, `tata-surya`, `kalimat-efektif`.

### A.5 `.env`

Minimal `kodmod-ai/.env` (dipakai oleh `create_test_db` / `seed_curriculum` /
`ingest_documents` yang jalan di luar notebook):

```
OPENAI_API_KEY=sk-...
DB_PORT=5433
```

`DB_PORT=5433` cocok dengan `docker-compose.test.yml`. Kalau kamu memakai
Postgres di 5432, hilangkan baris itu.

Sisanya (provider, path, flag TTS/STT) di-set oleh sel pertama notebook. Kalau
menjalankan script/FastAPI langsung, tambahkan juga:

```
DB_PORT=5433
KODMOD_LLM_PROVIDER=openai
KODMOD_EMBED_BACKEND=openai
KODMOD_EMBED_MODEL=text-embedding-3-small
KODMOD_EMBED_DIM=1024
VECTOR_BACKEND=pgvector
RAG_TOP_K=4
TTS_ENABLED=false
STT_ENABLED=false
KODMOD_TTS_OUTPUT_DIR=./.runtime/audio
AUDIO_DIR=./.runtime/audio
UPLOAD_DIR=./.runtime/uploads
```

### A.6 Jalankan notebook

`notebooks/text_mode_smoke.ipynb` — jalankan Jupyter dengan cwd `kodmod-ai/`:

```bash
python -m jupyter lab      # atau: code notebooks/text_mode_smoke.ipynb
```

Jalankan sel dari atas ke bawah. Tidak ada file `.wav` yang ditulis.

### A.7 Atau: chat CLI interaktif

`scripts/chat_cli.py` — REPL ala `ollama run`, bebas mencoba fitur mana saja:

```bash
python -m scripts.chat_cli
```

- teks bebas → satu giliran lewat graf (intent otomatis)
- `/quiz <concept> [diff]`, `/answer <jawaban>`, `/mini <concept>`
- `/analyze` (analisa kuis + update mastery), `/analytics`, `/mastery`
- `/history` (sisipkan riwayat contoh), `/concepts`, `/state`, `/reset`
- `/debug on` untuk traceback penuh, `/help`, `/quit`

Setiap fitur dibungkus penangan error: kalau gagal, CLI menampilkan pesan +
saran (mis. "id model OpenAI tidak valid → edit `tools/llm_client.py`") dan
REPL tetap jalan.

---

## B. Memasukkan dokumen RAG

Tanpa dokumen, `retrieved_docs` selalu kosong dan tutor menjawab tanpa grounding
kurikulum (tetap jalan). Untuk mengaktifkan grounding:

### B.1 Siapkan file

```bash
mkdir -p data/curriculum/sains
cat > data/curriculum/sains/fotosintesis.md <<'EOF'
# Fotosintesis
Fotosintesis adalah proses tumbuhan mengubah cahaya matahari, air, dan
karbon dioksida menjadi glukosa dan oksigen.
Proses ini terjadi di kloroplas di dalam daun. Klorofil adalah pigmen hijau
yang menangkap energi cahaya.
Glukosa dipakai tumbuhan sebagai sumber energi; oksigen dilepas ke udara.
EOF
```

Format yang didukung: `.md`, `.txt`, `.pdf` (PDF butuh `pypdf`, sudah di dependensi).
Chunking: `rag/chunking.py::chunk_document` — target ~350 "token" (≈1400 karakter),
overlap 1 kalimat, split keras pada heading (`#`..`####`, `Bab N`, `Bagian N`).

### B.2 Jalankan ingest

```bash
export KODMOD_EMBED_BACKEND=openai
export KODMOD_EMBED_MODEL=text-embedding-3-small
export KODMOD_EMBED_DIM=1024
export VECTOR_BACKEND=pgvector
export OPENAI_API_KEY=sk-...

python -m scripts.ingest_documents \
  --path data/curriculum/sains/fotosintesis.md \
  --language id
```

- **Tanpa `--concept-slug`** → `concept_id = NULL` (paling sederhana; cukup untuk uji).
- **Dengan `--concept-slug fotosintesis`** → chunk ditautkan ke concept itu; wajib
  sudah `seed_curriculum` dulu. Retrieval ber-filter concept baru dipakai bila state
  turn menyetel `current_concept_id`.
- Direktori juga boleh: `--path data/curriculum/` (rekursif, ambil `.md/.txt/.pdf`).

### B.3 Verifikasi

```sql
SELECT id, source, chunk_index, section_title,
       vector_dims(embedding) AS dims, left(content, 80) AS preview
FROM curriculum_chunks
ORDER BY created_at DESC
LIMIT 10;
```

`dims` harus `1024`. Smoke test retrieval (dari `kodmod-ai/`, env seperti di atas):

```python
import asyncio
from database.session import init_db, close_db
from rag.retriever import retrieve


async def main():
    await init_db()
    print(await retrieve("apa itu fotosintesis", use_reranker=False))
    await close_db()


asyncio.run(main())
```

Lalu di notebook, tanya topik itu lewat `run("Jelaskan fotosintesis",
current_concept_id=str(CONCEPTS["fotosintesis"]))` → `len(retrieved_docs) > 0`.

### B.4 Hapus / re-ingest

`rag/stores/pgvector_store.py::delete_by_source(path)` menghapus chunk dari satu file;
`upsert_chunks` memakai `ON CONFLICT (id)` sehingga re-ingest membuat baris baru
(id di-generate ulang) — untuk mengganti isi, hapus dulu berdasarkan `source`.

---

## C. Memicu fitur lewat REST (opsional)

`api/main.py` (FastAPI) **baru bisa start setelah patch `database/session.py`**, dan
tetap butuh Postgres + checkpointer LangGraph di `LANGGRAPH_DB_URI`.

```bash
python -m uvicorn api.main:app --port 8000
```

### C.1 Mint JWT (tidak ada route login)

```python
import jwt, uuid, time
from config.settings import settings

sid = "11111111-1111-1111-1111-111111111111"  # harus cocok baris students
tok = jwt.encode(
    {"sub": sid, "role": "student", "iat": int(time.time()), "exp": int(time.time()) + 86400},
    settings.JWT_SECRET,
    algorithm=settings.JWT_ALG,
)
print("Authorization: Bearer", tok)
```

`current_teacher` sama, `role="teacher"` + baris `teachers`.

### C.2 Endpoint yang berfungsi

| Method | Path | Auth | Catatan |
|---|---|---|---|
| GET | `/health/live` `/health/ready` `/health/version` | — | `ready` mengecek DB + Redis (Redis non-kritis). |
| POST | `/student` | — | Buat siswa (ORM). |
| GET | `/student/me` | student | Butuh baris siswa. |
| GET | `/content/concepts?subject_id=` | — | Butuh seed. |
| GET | `/content/concepts/{id}/lessons` | — | Butuh seed. |
| POST | `/content/retrieve` | — | RAG langsung (`rag.retriever.retrieve`). Butuh `curriculum_chunks` + embedding. |
| GET | `/analytics/student/{id}?window=week` | student | `id` harus == `sub` token. Siswa tanpa riwayat → nilai nol. |
| GET | `/analytics/student/{id}/spoken` | student | Ringkasan lisan Bahasa Indonesia. |
| GET | `/exercise/by-concept/{concept_id}` | — | Butuh baris `exercises` (seed tidak mengisi ini). |

### C.3 Endpoint yang MASIH rusak (jangan dipakai tanpa perbaikan lanjutan)

- `POST /voice/text`, `POST /voice/chat`, `POST /quiz/start`, `POST /quiz/submit` —
  semua menyetel `state["learning_profile"] = student.profile`, padahal ORM `Student`
  tidak punya atribut `profile` → `AttributeError`. `/quiz/start` juga punya
  `_load_mastery` yang meng-chain koroutin.
- `POST /exercise/generate` — memanggil `generate_questions_for_student` yang tidak
  didefinisikan di `agents/problem_generator.py`.

Untuk turn percakapan berbasis teks lewat HTTP, perbaiki `student.profile` dulu
(mis. `state["learning_profile"] = {}`), atau pakai notebook (jalur graf langsung).

---

## D. Status kesiapan (jawaban atas "apakah sistem sudah bisa dijalankan?")

**Belum, apa adanya.** Setelah patch di bagian A.1, mode teks lewat notebook berjalan
untuk semua fitur inti. Yang masih terbuka (di luar cakupan uji ini):

| Masalah | Dampak | Disiasati dengan |
|---|---|---|
| Jalur scoring quiz tak terjangkau dari START (`route_after_intent` tak punya cabang "quiz berjalan"; `mini_quiz` tak ada edge masuk) | Quiz multi-turn (jawab→skor→analisa) tidak jalan lewat `ainvoke` | Notebook memanggil `scoring_node`/`quiz_analyzer_node`/`update_student_model_node` langsung |
| `database/schema.sql` ≠ `database/models.py` | Dua skema tak kompatibel | Pakai `create_all` dari ORM saja; `schema.sql` tidak di-autoload |
| Route `/voice/*`, `/quiz/*` pakai `student.profile` yang tak ada | Turn percakapan via HTTP gagal | Pakai notebook; atau patch route |
| `generate_questions_for_student` tidak ada | `/exercise/generate` mati | — |
| `accessibility/narration.py::describe_image` pakai `get_tutor_llm(temperature=…)` | Narasi gambar (vision) gagal | Tidak dipakai di mode teks |
| `tests/integration/test_graph_wiring.py` belum benar (`await` hilang, `initial_state` kurang arg) | Test itu gagal | Bukan patokan; unit test lain hijau |
| FastAPI butuh checkpointer Postgres + `.env` untuk start | Tidak bisa "jalan langsung" tanpa infra | Notebook tidak butuh checkpointer (`checkpointer=None`) |

### Follow-up yang disarankan (isu terpisah)

1. Perbaiki routing graf untuk quiz multi-turn (butuh checkpointer Postgres).
2. Satukan `database/schema.sql` dengan `database/models.py` (atau buang salah satu).
3. Perbaiki jalur REST (`student.profile`, `_load_mastery`, `generate_questions_for_student`).
4. Ganti `gpt-5.6-luna` bila ternyata bukan id model OpenAI yang valid.
