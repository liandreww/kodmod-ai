# KODMOD AI — Master Test Plan & Test Specification

> Status: **v1.0 — spesifikasi** (badan test ditulis bertahap per stage di session berikutnya)
> Basis kode: branch `hanif`, ~15-node LangGraph `StateGraph`, FastAPI (7 REST router + 1 WebSocket),
> RAG (pgvector/Qdrant), analytics BKT, memory Postgres+Redis, voice STT/TTS.

Dokumen ini adalah **rencana pengujian "brutal"**: sistematis, berlapis, otomatis penuh,
dengan **urutan eksekusi eksplisit** supaya perbaikan bug bisa dilakukan iteratif sampai
sistem "siap dipakai". **Infra** (Postgres, Redis, llm-stub, opsional Qdrant) jalan di satu
Docker Compose project `kodmod-test`; **`db-init` dan `api` jalan native di host** (uvicorn
membaca source langsung) supaya perubahan kode tidak butuh `docker build`.

---

## 1. Ruang lingkup

### 1.1 Yang diuji (in scope)

| Area | Modul |
|---|---|
| Graph orchestration | `graphs/state.py`, `graphs/main_graph.py` (15 node + 3 conditional router) |
| Agent nodes | `agents/*` (intent_router, tutoring, quiz_agent, problem_generator, scoring_agent, quiz_analyzer, analytics_agent, recommendation_agent, accessibility_agent, reflection_agent) |
| RAG | `rag/chunking.py`, `rag/embeddings.py`, `rag/reranker.py`, `rag/retriever.py`, `rag/ingestion.py`, `rag/stores/{pgvector,qdrant}_store.py` |
| Analytics | `analytics/student_model.py` (BKT), `analytics/aggregator.py`, `analytics/insights.py` |
| Accessibility | `agents/accessibility_agent.py`, `accessibility/simplifier.py`, `accessibility/narration.py`, `accessibility/voice_commands.py` |
| Memory | `memory/short_term.py` (Redis), `memory/long_term.py` (Postgres), `memory/episodic.py` |
| Voice adapters | `voice/stt.py`, `voice/tts.py`, `voice/streaming.py` — **unit-level, lib di-mock** |
| API REST | `api/routes/{health,voice,quiz,student,analytics,exercise,content}.py` |
| API WebSocket | `api/websockets/voice_stream.py` (`/ws/voice`) |
| Auth | `api/dependencies.py` (JWT, `current_student`/`current_teacher`, `authenticate_ws`) |
| Config | `config/settings.py` |
| Data/persistence | `database/session.py`, `database/models.py`, `scripts/create_test_db.py`, `scripts/seed_curriculum.py` |
| Infra | `docker/Dockerfile`, `docker/docker-compose.test.yml`, lifespan `api/main.py` |

### 1.2 Di luar lingkup (out of scope)

- Engine STT/TTS sungguhan (piper, faster-whisper, deepgram, azure, elevenlabs, coqui) —
  **semua pengujian text-mode** (`STT_ENABLED=false`, `TTS_ENABLED=false`).
- Kualitas jawaban LLM sebagai model (evaluasi pedagogis mendalam) — hanya *smoke*
  `@real_llm` opsional.
- Beban model embedding/reranker nyata (BGE-M3 ~2.3 GB, GPU) — di-stub deterministik.
- Frontend / klien mobile (tidak ada di repo).
- DAST penuh (OWASP ZAP) — keamanan dinamis tingkat "Standar" saja.
- Load test terhadap provider LLM nyata (biaya) — beban diukur dengan `llm-stub`.

---

## 2. Keputusan strategi (dikonfirmasi)

| Topik | Keputusan | Konsekuensi |
|---|---|---|
| **LLM & embedding** | Stub-first. Fake chat model + fake embedding deterministik untuk **semua** level. Lapis tipis `@real_llm` (skip default) untuk 2–3 system smoke. | Suite cepat, gratis, deterministik, jalan tanpa API key. Fidelitas latency model tidak diukur — dianggap dapat diterima. |
| **Oracle test case** | Perilaku **target/spesifikasi**. Bug diketahui tapi belum di-fix → tetap `assert` biasa (jadi **MERAH**) + `@pytest.mark.known_bug("#n")`. **Tidak** pakai `xfail`. | Test = backlog perbaikan + definition-of-done. Merah = bug masih ada; hijau = sudah di-fix (tak ada penanda yang perlu dicabut). Runner stage pakai `-m "<marker> and not known_bug"` supaya tetap bisa lanjut; `make test-burndown` (`-m known_bug`) menghitung sisa. |
| **Mode suara** | Text-mode di semua pengujian. Adapter voice diuji unit dgn lib di-mock; WebSocket pakai transcript sintetis. | Tidak ada instalasi piper/faster-whisper/model di image test. |
| **Keamanan dinamis** | Tingkat **Standar**: authz/authn + injeksi SQL/SSRF/DoS berbasis pytest + fuzzing Schemathesis. | Scan statis (bandit, pip-audit, safety, detect-secrets, Trivy) tetap wajib di Stage 0. Tanpa ZAP. |

---

## 3. Level & urutan pengujian

Sepuluh stage + gate rilis. **Prinsip urutan:** *fail-fast menurut kedalaman dependensi &
blast-radius.* Gate paling murah & paling memblokir dijalankan lebih dulu.

| # | Stage | Spec | Butuh service | Durasi target | Sifat gate |
|---|---|---|---|---|---|
| 0 | Static & Build | [`00-static.md`](00-static.md) | — | < 90 s | **blok total** |
| 1 | Unit (logika murni) | [`01-unit.md`](01-unit.md) | — | < 30 s | blok |
| 2 | Contract / Schema | [`02-contract.md`](02-contract.md) | — | < 30 s | blok |
| 3 | Integration | [`03-integration.md`](03-integration.md) | Docker: postgres, redis, llm-stub · host: schema+seed | 2–5 min | blok |
| 4 | API / Endpoint | [`04-api.md`](04-api.md) | + host: `api` (`serve_test_api`) | 3–6 min | blok |
| 5 | WebSocket / Realtime | [`05-ws.md`](05-ws.md) | + host: `api` | 1–2 min | blok |
| 6 | E2E user journey | [`06-e2e.md`](06-e2e.md) | + host: `api` | 2–5 min | blok |
| 7 | System (black-box) | [`07-system.md`](07-system.md) | + host: `api` (restart via pidfile), + qdrant | 5–10 min | blok |
| 8 | Performance / Load | [`08-performance.md`](08-performance.md) | + host: `api`, + locust (Docker) | 10–30 min | non-blok (baseline + ambang regresi) |
| 9 | Security (dinamis) | [`09-security.md`](09-security.md) | + host: `api` | 3–8 min | blok (0 High/Critical) |
| 10 | Release Readiness Gate | [`10-readiness.md`](10-readiness.md) | all | — | gate rilis |

### 3.1 Kenapa urutan ini

1. **Stage 0** menangkap kelas bug yang membuat *segalanya* gagal collect: dead import
   (`StudentProfileTool`, `generate_questions_for_student`, `QdrantStore`), `SettingsError`
   dari `.env`, CVE dependensi, rahasia ter-commit. Tidak ada gunanya menjalankan test lain
   sebelum ini hijau.
2. **Stage 1** mengunci fondasi semantik (matematika BKT, chunking, router, helper
   aksesibilitas). Cepat, tanpa I/O — dijalankan sangat sering saat perbaikan.
3. **Stage 2** memastikan *bentuk* benar sebelum menyentuh I/O: skema Pydantic, konsistensi
   `response_model`, graph ter-compile, **semua node reachable dari `START`**.
4. **Stage 3** membangun fondasi data: DB layer, memory, analytics, RAG store, tiap node
   terisolasi, lalu graph utuh per intent. Butuh Postgres + Redis nyata.
5. **Stage 4–5** menguji API & WebSocket di atas fondasi data yang sudah terbukti.
6. **Stage 6** merangkai journey pengguna nyata end-to-end (text-mode).
7. **Stage 7** menguji sistem sebagai kotak hitam (compose penuh): healthcheck, lifespan,
   **persistensi lintas restart**, matriks backend.
8. **Stage 8–9** butuh sistem yang *sudah jalan* agar bermakna: beban & keamanan dinamis.
9. **Stage 10** gerbang rilis: coverage, burndown bug, regresi perf, scan bersih,
   traceability lengkap.

### 3.2 Loop perbaikan iteratif

```powershell
pwsh scripts/run_tests.ps1           # Windows — jalan Stage 0 → 10, BERHENTI di stage MERAH pertama
# perbaiki penyebab
pwsh scripts/run_tests.ps1 -From N   # lanjut dari stage N
```

```bash
bash scripts/run_tests.sh            # setara, untuk bash / CI
bash scripts/run_tests.sh --from N
```

Kedua skrip jalan **native di host** — tidak ada langkah yang menjalankan pytest di dalam
kontainer. Mereka hanya memanggil `docker compose` untuk menaikkan service yang dibutuhkan
tiap stage.

Setiap iterasi: satu stage merah → perbaiki akar masalah → stage itu hijau → lanjut.
Test `known_bug` di-*exclude* dari gerbang stage (`-m "<marker> and not known_bug"`), jadi
stage bisa hijau sambil backlog masih ada; jalankan `make test-burndown` untuk melihat
sisa bug (FAIL = belum di-fix, PASS = sudah — cabut penanda `known_bug`-nya).
Sistem **"siap dipakai" = Stage 10 hijau** DAN `make test-burndown` 0 FAIL / 0 PASS
(semua bug bertarget-rilis di-fix dan penandanya dicabut), coverage & scan lolos.

---

## 4. Lingkungan uji — infra di Docker, `db-init` + `api` di host

**Infra** — Postgres+pgvector, Redis, llm-stub, (Qdrant) — jalan lewat
`docker/docker-compose.test.yml` (project name **`kodmod-test`**). Tak satu pun image itu
membawa source aplikasi, jadi tidak pernah butuh rebuild saat kode berubah.

**Backend tidak ada di compose.** `db-init` (schema + seed) dan `api` (uvicorn) jalan
**native di host**:
- `python -m scripts.init_test_db` — kunci env test lalu bootstrap skema ORM +
  `curriculum_chunks` + seed kurikulum (idempoten). Membungkus `scripts.create_test_db`
  + `scripts.seed_curriculum` dengan `DB_NAME=kodmod_test` dipaksa (bukan `kodmod` dari `.env`).
- `python -m scripts.serve_test_api` — `uvicorn api.main:app` dengan env test terkunci
  (`os.environ.setdefault` sebelum import `config.settings`, menang atas `.env` on-disk),
  LLM/embed → `llm-stub` di `http://localhost:8099/v1`, pidfile `reports/.api.pid`. Membaca
  source langsung → perubahan kode = restart proses, **tanpa `docker build`**.

**Skrip pengujian (pytest, locust) TIDAK dijalankan di dalam container.** Dijalankan native
di host — PowerShell (`scripts/run_tests.ps1`) atau bash (`scripts/run_tests.sh`, juga
dipakai CI). Keduanya yang mengurus start/stop proses `api` host untuk Stage 4+:
- Stage 1 (unit): tidak butuh service apa pun.
- Stage 3 (integration): memanggil fungsi Python langsung di proses pytest, tersambung ke
  Postgres/Redis lewat port host.
- **Stage 4–9** (api/ws/e2e/system/perf/security): pytest memanggil proses `api` host lewat
  **HTTP/WS sungguhan** (`http://localhost:8000`, `ws://localhost:8000/ws/voice`) — proses
  terpisah, bukan import in-process/`ASGITransport`, jadi tetap black-box.

Dijalankan dari `kodmod-ai/`:

```powershell
# 1. infra
docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub
# 2-4. schema+seed, api host, lalu semua stage — di-orkestrasi oleh:
pip install -e ".[test]"
pwsh scripts/run_tests.ps1          # Windows
# atau: bash scripts/run_tests.sh   # bash / CI
```

```bash
# matriks backend qdrant (Stage 7 saja)
docker compose -p kodmod-test -f docker/docker-compose.test.yml --profile qdrant up -d

# beban (Stage 8) — jalankan setelah api host hidup di :8000
docker compose -p kodmod-test -f docker/docker-compose.test.yml --profile load up -d locust
```

**Service Docker** (`docker/docker-compose.test.yml`):

| Service | Image / build | Peran | Profile |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | DB + pgvector. `POSTGRES_DB=kodmod_test`, `POSTGRES_USER/PASSWORD=kodmod`. Host port **5433**. Healthcheck `pg_isready`. **Tidak** mount `schema.sql`. | default |
| `redis` | `redis:7-alpine` | Session store. Host port **6380**. Healthcheck `redis-cli ping`. | default |
| `qdrant` | `qdrant/qdrant:v1.10.1` | Matriks `VECTOR_BACKEND=qdrant` (Stage 7). Host port **6335**. | `qdrant` |
| `llm-stub` | build `docker/llm_stub/` | Fake OpenAI-compatible: `/v1/chat/completions`, `/v1/embeddings` (1024-dim), `/health`. Deterministik per hash prompt. Host port **8099**. | default |
| `locust` | `locustio/locust` | Beban terhadap `api` host via `host.docker.internal:8000`. | `load` |

**Proses host** (bukan container):

| Proses | Perintah | Peran |
|---|---|---|
| db-init | `python -m scripts.init_test_db` | Skema ORM + `curriculum_chunks` DDL + seed kurikulum (idempoten); env test dikunci. |
| api | `python -m scripts.serve_test_api` | `uvicorn api.main:app`, env test, `:8000`, pidfile `reports/.api.pid`. Wajib hidup mulai Stage 4. |

**Rekonsiliasi environment:**

| Masalah asli | Perbaikan di lingkungan test |
|---|---|
| `conftest` set `DB_NAME=kodmod_test`, compose lama `POSTGRES_DB=kodmod` | `POSTGRES_DB=kodmod_test` + `DB_NAME=kodmod_test` konsisten |
| `.env` on-disk `EMBEDDING_DIM=1536` vs kolom `vector(1024)` | `EMBEDDING_DIM=1024` dipaksa: env compose (infra) + `scripts/serve_test_api` (api host) |
| `.env` on-disk berisi `OPENAI_API_KEY` & `JWT_SECRET` asli | `scripts/serve_test_api` mengunci env test via `os.environ.setdefault` **sebelum** import `config.settings` (menang atas `.env`); key asli hanya via shell/CI secret untuk `@real_llm` |
| `schema.sql` ≠ ORM `models.py` | skema test dari `create_test_db.py` (ORM `create_all` + DDL `curriculum_chunks`), **bukan** `schema.sql` |
| default `alembic upgrade head` no-op (tidak ada `versions/`) | tidak dipakai untuk bootstrap test |

---

## 5. Framework & tooling

| Kebutuhan | Alat | Status |
|---|---|---|
| Runner | `pytest` + `pytest-asyncio` (`asyncio_mode=auto`) | sudah ada |
| Coverage | `pytest-cov` + `coverage combine` lintas stage | sudah ada |
| Paralel / stabilitas | `pytest-xdist`, `pytest-randomly`, `pytest-timeout` | **tambah** |
| Mock | `pytest-mock`, `respx` (stub HTTP keluar) | **tambah** |
| HTTP client | `httpx.AsyncClient(base_url="http://localhost:8000")` — HTTP nyata ke proses `api` host (Stage 4-9); tanpa `ASGITransport` | httpx sudah dep inti |
| WebSocket client | `httpx-ws` / paket `websockets` ke `ws://localhost:8000/ws/voice` nyata (proses `api` host) | **tambah `httpx-ws`** |
| Stub LLM | `langchain_core.language_models.fake_chat_models.GenericFakeChatModel` + wrapper `with_structured_output` | pustaka sudah ada |
| Stub embedding | fungsi hash→vektor 1024 float deterministik | tulis di `tests/_fakes/` |
| API contract/fuzz | `schemathesis` (dari `/openapi.json`) | **tambah** |
| Load | `locust` | **tambah** |
| Micro-bench | `pytest-benchmark` | **tambah** |
| SAST | `bandit` + ruff rule set `S` | **tambah** |
| Dependency CVE | `pip-audit`, `safety` | **tambah** |
| Secret scan | `detect-secrets` (+ `gitleaks` action di CI) | **tambah** |
| Image/FS scan | `trivy` (CI action / image) | CI |
| Type check | `mypy` | sudah ada |

Ditambahkan ke `pyproject.toml` sebagai extra baru `[project.optional-dependencies].test`
(extra `dev` tetap dipertahankan): `pytest-xdist`, `pytest-randomly`, `pytest-timeout`,
`pytest-mock`, `anyio`, `httpx-ws`, `schemathesis`, `locust`, `pytest-benchmark`, `respx`,
`bandit`, `pip-audit`, `safety`, `detect-secrets`.

---

## 6. Konvensi test

### 6.1 ID & marker

- **ID**: `KM-<STAGE>-<NNN>` — `STATIC, UNIT, CONTRACT, INT, API, WS, E2E, SYS, PERF, SEC, READY`.
- **Marker pytest** (didaftarkan di `pyproject.toml`): `unit`, `contract`, `integration`,
  `api`, `ws`, `e2e`, `system`, `perf`, `security`, `real_llm`, `slow`, `db`, `redis`,
  `known_bug`.
- **Perilaku target belum diperbaiki** (kebijakan sejak 2026-09-02 — **bukan lagi `xfail`**):
  test tetap asersi biasa terhadap perilaku target, jadi ia **MERAH** selama bug belum
  di-fix, lalu **HIJAU** begitu di-fix (tak ada penanda yang perlu dicabut). Tandai
  `@pytest.mark.known_bug("BUG L-xx / #n — <ringkas>")` supaya:
  - runner stage bisa mengecualikannya (`-m "<marker> and not known_bug"`) → stage tetap
    menggerbang **regresi**, bukan backlog;
  - `make test-burndown` (`pytest -m known_bug`) memberi laporan: FAIL = bug masih terbuka,
    PASS = sudah di-fix (hapus penanda `known_bug`-nya).
  Catatan: anotasi `→ xfail(strict)` di katalog stage 02–09 (ditulis sebelum kebijakan ini)
  dibaca sebagai "**asersi biasa + `@pytest.mark.known_bug`**".

### 6.2 Format katalog test case (di tiap `NN-*.md`)

| Kolom | Isi |
|---|---|
| ID | `KM-<STAGE>-<NNN>` |
| Judul | frasa singkat |
| Prasyarat | fixture / state awal |
| Langkah | aksi ringkas |
| Hasil diharapkan | asersi utama |
| Oracle | dari mana kebenaran ditentukan (spec / rumus / kontrak model / dokumen) |
| Bug ref | `L-xx` / `#n` bila relevan |
| Marker | daftar marker + `known_bug?` (bug belum di-fix → test MERAH) |

### 6.3 Isolasi & determinisme

- DB: tiap test dibungkus transaksi + `SAVEPOINT`, di-rollback di teardown. Tidak ada test
  yang bergantung pada urutan (`pytest-randomly` membuktikannya).
- Redis: `flushdb` di setup & teardown fixture `redis_client`.
- Waktu: bekukan via `freezegun`/`monkeypatch` untuk test decay & TTL bila perlu.
- LLM/embedding: fixture autouse `stub_llms` + `stub_embeddings`; hanya marker `real_llm`
  yang melepasnya (dan itu pun `skip` kecuali `KODMOD_RUN_REAL_LLM=1`).
- Semua node graph & DB call `async` → `pytest-asyncio` `asyncio_mode=auto`.

---

## 7. Entry / Exit criteria global

**Entry (mulai kampanye pengujian):**
- `docker compose -p kodmod-test -f docker/docker-compose.test.yml config` valid.
- `pip install -e ".[test]"` sukses di Python 3.11.
- `python -m scripts.serve_test_api` boot bersih ke `/live` 200 (setelah infra + schema+seed).
- `docs/testplan/*` (dokumen ini + 00–10 + traceability + test-data) tersedia.

**Exit (sistem "siap dipakai") — Stage 10 hijau:**
- Stage 0–7 & 9 seluruhnya hijau (`-m "<marker> and not known_bug"`).
- `pytest -m known_bug` (burndown) **0 FAIL** untuk bug bertarget-rilis, lalu penanda
  `known_bug` dicabut sehingga tak ada `known_bug` tersisa di suite rilis.
- Coverage: modul logika murni ≥ 90 %, keseluruhan ≥ 75 % (angka final disepakati tim).
- Stage 8: metrik dalam ±25 % baseline tersimpan; tidak ada kebocoran pada soak 30 menit.
- Stage 9 + scan Stage 0: 0 temuan High/Critical tanpa *waiver* bertanggal.
- `traceability.md`: 0 baris requirement/bug tanpa minimal 1 Test ID.
- `pytest -p randomly -n auto` seluruh suite hijau.

---

## 8. Peran & artefak

| Peran | Tanggung jawab |
|---|---|
| Test lead | menjaga urutan stage, meninjau `traceability.md`, memutuskan *waiver* |
| Dev | memperbaiki akar bug per stage merah; setelah `known_bug` test jadi hijau, cabut penandanya |
| CI | menjalankan Stage 0–7 + 9 tiap PR; Stage 8 nightly/manual |

**Artefak yang dihasilkan tiap run:**
- `reports/junit-<stage>.xml`, `reports/coverage-<stage>.xml`, `htmlcov/`
- `reports/bandit.json`, `reports/pip-audit.json`, `reports/schemathesis-<stage>.tap`
- `docs/testplan/baselines/*.json` (pytest-benchmark + ringkasan Locust)
- `reports/junit-known-bug.xml` + `reports/burndown.md` (auto: daftar test `known_bug` — FAIL=terbuka, PASS=beres — per tag bug)

---

## 9. Risiko & mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Banyak bug struktural (graph unreachable, `student.profile`, quiz field) | Stage 2–6 merah beruntun sejak awal | test bug diketahui ditandai `known_bug` (di-exclude dari gerbang stage, muncul di `make test-burndown`); perbaikan iteratif per stage |
| `schema.sql` ≠ ORM | drift skema | test hanya terhadap ORM; `schema.sql` ditandai *deprecated* di `03-integration.md` |
| Stub LLM terlalu "bodoh" untuk node yang parsing JSON ketat | node gagal parse → false negative | fake chat model per-peran memuat contoh output valid (JSON/структур) sesuai prompt tiap agen; lihat `tests/_fakes/fake_chat.py` |
| `@lru_cache` pada getter LLM & `_model()` embedding | monkeypatch tak berefek | patch **nama di modul pemakai**, bukan sumber; `cache_clear()` di fixture |
| Windows dev vs Linux CI (path) | flaky lokal | `scripts/serve_test_api` set `AUDIO_DIR`/`UPLOAD_DIR` ke `./.runtime/...` relatif repo (dibuat otomatis), sama di Windows & Linux; pytest jalan native di host dan tidak menyentuh path itu langsung — semua akses lewat HTTP ke `api` |
| Rahasia asli di `.env` on-disk | kebocoran | `detect-secrets` menandainya (KM-STATIC-021) + isu rotasi wajib; env test tidak membaca `.env` |
| Load test dgn `llm-stub` tidak mencerminkan latency nyata | SLO menyesatkan | dokumentasikan eksplisit: Stage 8 mengukur overhead framework/DB/checkpointer, bukan model |

---

## 10. Indeks dokumen

| File | Isi |
|---|---|
| [`00-static.md`](00-static.md) | Static & build gates |
| [`01-unit.md`](01-unit.md) | Unit test logika murni |
| [`02-contract.md`](02-contract.md) | Skema Pydantic, konsistensi API, wiring graph |
| [`03-integration.md`](03-integration.md) | DB/Redis/RAG/analytics/node/graph dgn infra nyata |
| [`04-api.md`](04-api.md) | Endpoint REST + auth matrix + Schemathesis |
| [`05-ws.md`](05-ws.md) | WebSocket `/ws/voice` |
| [`06-e2e.md`](06-e2e.md) | Journey pengguna text-mode |
| [`07-system.md`](07-system.md) | Black-box compose, lifespan, persistensi |
| [`08-performance.md`](08-performance.md) | Locust, benchmark, saturasi, soak |
| [`09-security.md`](09-security.md) | AuthZ/AuthN, injeksi, SSRF, DoS, CORS |
| [`10-readiness.md`](10-readiness.md) | Gate rilis |
| [`traceability.md`](traceability.md) | Requirement/Bug → Test ID → Stage |
| [`test-data.md`](test-data.md) | Dataset seed & fixture data |
