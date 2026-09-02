# Test Data & Fixtures

Semua data uji **deterministik** dan dibuat via fixture/skrip — tidak ada dependensi pada
database dev. Seed kurikulum memakai `scripts/seed_curriculum.py` yang sudah idempoten.

---

## 1. UUID tetap (dipakai lintas stage)

| Nama | UUID | Peran |
|---|---|---|
| `STUDENT_BLIND` | `11111111-1111-1111-1111-111111111111` | siswa utama, `accessibility_profile="blind"`, `preferred_language="id"` |
| `STUDENT_LOWVISION` | `11111111-1111-1111-1111-111111111112` | siswa kedua (IDOR target) |
| `STUDENT_STRONG` | `11111111-1111-1111-1111-111111111113` | profil mastery tinggi (analytics) |
| `TEACHER_A` | `22222222-2222-2222-2222-222222222221` | guru (endpoint teacher) |
| `CLASSROOM_A` | `33333333-3333-3333-3333-333333333331` | kelas berisi 3 siswa di atas |
| `CONCEPT_PECAHAN` | di-resolve dari slug `pecahan` saat runtime | konsep RAG & kuis utama |

> `analytics/student_model.py` memakai `CAST(:sid AS uuid)` — semua id di atas valid UUID v4-shaped.

## 2. Konsep hasil seed (`scripts/seed_curriculum.py`)

Slug tersedia setelah `python -m scripts.seed_curriculum`:
`pecahan`, `persamaan-linear`, `bangun-datar`, `fotosintesis`, `tata-surya`, `kalimat-efektif`.

Subjek: Matematika, Sains, Bahasa Indonesia (data sampel Bahasa Indonesia).

## 3. Fixture factory (di `tests/conftest.py`)

| Fixture | Menghasilkan |
|---|---|
| `student_factory(**overrides)` | insert ORM `Student`; return `(student, token)` — `token` = JWT `{sub, role:"student", iat, exp:+3600}` di-sign `settings.JWT_SECRET`/`JWT_ALG` |
| `teacher_factory(**overrides)` | idem untuk `Teacher`, `role:"teacher"` |
| `auth_headers(token)` | `{"Authorization": f"Bearer {token}"}` |
| `seed_mastery(student_id, mapping)` | upsert `mastery_scores` (`mastery`, `confidence`, `n_attempts`, `last_seen`) |
| `seed_sessions(student_id, n, window)` | `LearningSession` + `QuizSession`/`QuizQuestion`/`QuizAttempt` untuk analytics |
| `seed_chunks(concept_id, texts, language="id")` | `upsert_chunks` dgn embedding **stub** 1024-dim |
| `ingest_doc(path, concept_id)` | wrapper `rag.ingestion.ingest_paths` (embedding stub) |

### Profil mastery contoh

```python
MASTERY_WEAK = {"pecahan": 0.25, "persamaan-linear": 0.30, "bangun-datar": 0.35}
MASTERY_MIXED = {"pecahan": 0.55, "fotosintesis": 0.80, "tata-surya": 0.40}
MASTERY_STRONG = {"pecahan": 0.90, "fotosintesis": 0.88, "kalimat-efektif": 0.85}
```

## 4. Dokumen RAG mini — `data/testplan/pecahan_mini.md`

~300 kata, 2 heading, 1 referensi gambar (untuk menguji stripping aksesibilitas &
`referenced_figures`). Konten dipakai KM-INT-096, KM-E2E-005.

```markdown
# Pengertian Pecahan

Pecahan adalah bilangan yang menyatakan bagian dari keseluruhan. Sebuah pecahan
ditulis sebagai a per b, dengan a disebut pembilang dan b disebut penyebut.
Penyebut tidak boleh nol. Contoh: satu per dua berarti satu bagian dari dua bagian
yang sama besar.

Pecahan senilai adalah pecahan yang memiliki nilai sama meskipun pembilang dan
penyebutnya berbeda. Contohnya, satu per dua senilai dengan dua per empat.

## Membandingkan Pecahan

Untuk membandingkan dua pecahan dengan penyebut sama, bandingkan pembilangnya.
Untuk penyebut berbeda, samakan penyebut terlebih dahulu. Lihat Gambar 1 untuk
ilustrasi garis bilangan pecahan.

## Penjumlahan Pecahan

Menjumlahkan pecahan berpenyebut sama dilakukan dengan menjumlahkan pembilang dan
mempertahankan penyebut. Untuk penyebut berbeda, cari kelipatan persekutuan
terkecil dari kedua penyebut, ubah menjadi pecahan senilai, lalu jumlahkan.
```

**Asersi terkait:**
- `chunk_document` → ≥ 3 chunk; chunk "Membandingkan Pecahan" punya `referenced_figures`
  memuat `"Gambar 1"`.
- Jawaban tutor berbasis dokumen ini **tidak** menyebut "lihat Gambar 1" (di-strip
  `accessibility_node`).

## 5. Pool utterance (Locust & E2E)

```
"jelaskan apa itu pecahan"
"bagaimana cara menjumlahkan pecahan berbeda penyebut"
"apa itu pecahan senilai"
"beri aku contoh soal pecahan"
"ulangi penjelasan tadi"
"lebih pelan"
"berhenti"
```

## 6. Payload keamanan (Stage 9)

| Kategori | Contoh nilai |
|---|---|
| SQLi | `' OR '1'='1`, `'; DROP TABLE curriculum_chunks;--`, `1) UNION SELECT ...` |
| SSRF | `http://169.254.169.254/latest/meta-data/`, `http://localhost:8000/metrics`, `http://[::1]/`, `http://kodmod-postgres-test:5432`, `file:///etc/passwd`, `gopher://x` |
| Path traversal | `../../etc/passwd`, `..\\..\\windows\\win.ini`, `%2e%2e%2f` |
| JWT jahat | `alg=none`; secret salah; `exp` lampau; `sub` = `"'; DROP"`; `aud`/`iss` asing |
| Oversize | body JSON 50 MB; upload 200 MB; WS frame 20 MB; header 8 KB × 100 |
| CRLF | `nilai\r\nX-Injected: 1` |

## 7. Konfigurasi environment test

Dua tempat berbeda — kodmod-ai jalan penuh di Docker, pytest jalan native di host:

**(a) Host, proses pytest** (Stage 1/3; `tests/conftest.py` men-set default via
`os.environ.setdefault`, override lewat env asli/`.env` lokal bila perlu):

```
ENV=test
DEBUG=false
DB_HOST=localhost                 # port-mapped ke container postgres
DB_PORT=5433
DB_USER=kodmod
DB_PASSWORD=kodmod
DB_NAME=kodmod_test
REDIS_HOST=localhost              # port-mapped ke container redis
REDIS_PORT=6380
KODMOD_LLM_PROVIDER=anthropic     # tak dipakai jaringan — dipatch stub_llms di proses pytest
ANTHROPIC_API_KEY=test-key
EMBEDDING_DIM=1024
VECTOR_BACKEND=pgvector
STT_ENABLED=false
TTS_ENABLED=false
LANGCHAIN_TRACING_V2=false
JWT_SECRET=test-secret-not-for-prod-0123456789abcdef
KODMOD_API_BASE_URL=http://localhost:8000   # dipakai fixture client/ws_url Stage 4-9
```

**(b) Container `api`** (Stage 4-9 — di-set di `x-app-env` / service `api` pada
`docker/docker-compose.test.yml`, LLM/embedding default ke `llm-stub`):

```
ENV=test
DB_HOST=postgres
DB_PORT=5432
DB_NAME=kodmod_test
REDIS_HOST=redis
KODMOD_LLM_PROVIDER=vllm
VLLM_BASE_URL=http://llm-stub:8000/v1
KODMOD_EMBED_BACKEND=openai
OPENAI_BASE_URL=http://llm-stub:8000/v1
EMBEDDING_DIM=1024
STT_ENABLED=false
TTS_ENABLED=false
JWT_SECRET=test-secret-not-for-prod-0123456789abcdef
```

`@real_llm` variant: naikkan ULANG container `api` dengan provider nyata di shell host
sebelum `docker compose up` (di-`skip` di sisi pytest kecuali `KODMOD_RUN_REAL_LLM=1`):

```powershell
$env:KODMOD_LLM_PROVIDER = "anthropic"
$env:ANTHROPIC_API_KEY   = "<dari secret CI, jangan commit>"
docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d --build api
```

Tetap `STT_ENABLED=false`, `TTS_ENABLED=false` — text-mode di semua kondisi.
