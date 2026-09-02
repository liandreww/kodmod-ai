# Stage 7 — System Test (black-box, compose penuh)

**Tujuan.** Menguji sistem sebagai **kotak hitam**: kontainer `api` yang dibangun dari
`docker/Dockerfile` dijalankan lewat compose bersama Postgres+Redis(+Qdrant), diakses hanya
via HTTP/WS. Memverifikasi healthcheck, lifespan (`init_db` + `AsyncPostgresSaver.setup` +
`build_kodmod_graph`), **persistensi state lintas restart kontainer**, matriks backend
vektor, endpoint operasional (`/metrics`), format log, dan shutdown anggun.

**Sifat gate.** Blok. 5–10 menit.

**Framework.** `pytest` sebagai driver, dijalankan native di host (PowerShell/bash) — **bukan**
di dalam kontainer. Memakai `httpx` + `docker` CLI (via `subprocess`) atau
`python-on-whales`/`docker` SDK untuk mengontrol compose (start/stop/restart/logs). LLM &
embedding kontainer `api` diarahkan ke service `llm-stub` (`KODMOD_LLM_PROVIDER=vllm` +
`VLLM_BASE_URL=http://llm-stub:8000/v1`, `KODMOD_EMBED_BACKEND=openai` +
`OPENAI_BASE_URL=http://llm-stub:8000/v1`).

**Entry.** Stage 6 hijau. **Exit.** Semua hijau; persistensi lintas restart terbukti; kedua
backend vektor jalan.

**Lokasi.** `tests/system/`. **Marker.** `system`, `slow`.

**Menjalankan.**
`docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d --build api`
(menaikkan seluruh stack — `api` tak lagi di belakang profile) lalu, native di host,
`pwsh scripts/run_tests.ps1 -Only 7` atau `pytest -m system`.

---

## Katalog test case

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SYS-001 | Boot & healthy | `up -d`; poll `GET http://localhost:8000/live` | 200 dalam < 60 s; `docker inspect` health = `healthy` | Dockerfile HEALTHCHECK `/health/live` — **catat**: Dockerfile pakai `/health/live` tapi route nyata `/live` → healthcheck mungkin gagal → `xfail(strict)` (target: samakan path) | #13 |
| KM-SYS-002 | Lifespan sukses | tail log kontainer `api` saat start | baris menandakan: `configure_logging`, `init_db` OK (SELECT 1), `AsyncPostgresSaver.setup()` OK, `build_kodmod_graph` OK; tidak ada traceback | `api/main.py` lifespan | — |
| KM-SYS-003 | Checkpoint tables dibuat | `psql` ke Postgres test → `\dt` | tabel checkpoint LangGraph (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs` atau setara) ada | `checkpointer.setup()` | — |
| KM-SYS-004 | `GET /ready` end-to-end | curl | 200; `checks.db=true`, `checks.redis=true` | health handler | — |
| KM-SYS-010 | Persistensi lintas restart | (a) `POST /voice/text` `text="halo"` header student, catat `session_id`; (b) `docker restart kodmod-api`; tunggu healthy; (c) `POST /voice/text` `text="ulangi"` dgn `session_id` sama | respons langkah (c) memakai konteks dari (a) — checkpoint di Postgres bertahan; `messages` thread berlanjut | `AsyncPostgresSaver` + `thread_id` | — |
| KM-SYS-011 | Interrupt HITL bertahan restart | jalankan turn yang berhenti di `interrupt_after=["reflection"]`; restart; resume `thread_id` | turn lanjut ke `accessibility→tts`, tidak mengulang dari awal | compile `interrupt_after` | — |
| KM-SYS-012 | Idempotensi `init_db`/`setup` saat restart | restart 3× | tidak ada error "table already exists"/"relation exists"; boot tetap < 60 s | idempoten | — |
| KM-SYS-020 | Matriks backend: pgvector (default) | `POST /content/retrieve` setelah ingest | 200, chunk relevan | `VECTOR_BACKEND=pgvector` | — |
| KM-SYS-021 | Matriks backend: qdrant | naikkan profile `qdrant`; set `VECTOR_BACKEND=qdrant`, `QDRANT_URL=http://qdrant:6333`; re-ingest; `POST /content/retrieve` | 200, chunk relevan | `rag/stores/qdrant_store.py` — **catat**: `RAGTool` import `QdrantStore` (tak ada) → jalur via `RAGTool` mati; `rag.retriever` pakai fungsi modul → jalur retriever OK. Uji **retriever**, tandai `RAGTool`+qdrant `xfail` | #9 |
| KM-SYS-030 | `/metrics` Prometheus | `GET /metrics` | 200 `text/plain; version=0.0.4`; memuat counter HTTP request; naik setelah beberapa request | `prometheus_client.make_asgi_app` | — |
| KM-SYS-031 | `/metrics` tanpa auth (kontrol) | `GET /metrics` tanpa header | 200 (tidak diproteksi) — dicatat, ditindak KM-SEC-062 | mount | #14 |
| KM-SYS-040 | Format log JSON | `LOG_JSON=true` di env kontainer; ambil 20 baris log | tiap baris `json.loads` sukses; ada field level/timestamp/logger | `config.logging._JsonFormatter` (rujukan `docker/log_conf.json`) | — |
| KM-SYS-041 | Log tidak bocor rahasia | grep log untuk `Bearer `, `JWT_SECRET`, `sk-`, `api_key` | 0 kecocokan | kebijakan | #15 |
| KM-SYS-050 | Shutdown anggun | `docker stop kodmod-api` (SIGTERM via `tini`) | exit code 0; log menandakan `checkpointer_cm.__aexit__` + `close_db`; tidak ada koneksi Postgres menggantung (`SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE '%kodmod%'` → 0 setelah beberapa detik) | lifespan shutdown | — |
| KM-SYS-051 | `depends_on` healthcheck | `up` tanpa `-d`, amati urutan | `db-init` jalan setelah `postgres` healthy; `api` start setelah `db-init` selesai & `redis` healthy | compose `depends_on` conditions | — |
| KM-SYS-052 | `db-init` idempoten | jalankan `db-init` 2× (`up db-init` lagi) | tidak error (`CREATE TABLE IF NOT EXISTS`, seed idempoten) | `create_test_db.py` + `seed_curriculum.py` | — |
| KM-SYS-060 | Config `ENV` non-test | jalankan kontainer `api` dgn `ENV=staging` (pool aktif, bukan NullPool) | boot OK; `GET /version` `env=staging` | `settings` | — |
| KM-SYS-061 | Reject startup tanpa DB | start `api` tanpa `postgres` | `init_db` `SELECT 1` gagal → proses exit non-zero cepat (fail-fast), bukan hang | `init_db` raise | — |
| KM-SYS-062 | Reject startup tanpa checkpointer DB | `LANGGRAPH_DB_URI` menunjuk DB mati | `AsyncPostgresSaver.setup()` gagal → exit non-zero | lifespan | — |
| KM-SYS-070 | Image non-root & minim | `docker inspect` / `docker run whoami` | user `kodmod` (uid 1001); `ffmpeg`/`libsndfile1` ada; tidak ada toolchain build di runtime stage | `docker/Dockerfile` | — |
| KM-SYS-071 | Ukuran & layer image | `docker image inspect` | ukuran wajar (< ~1.5 GB tanpa torch/model); catat baseline | Dockerfile multi-stage | — |

---

## Catatan implementasi

- Driver `tests/system/conftest.py`: fixture session `compose_stack` → `docker compose ... up -d --build`,
  tunggu `api` healthy (poll `/live`), yield, `docker compose ... down -v` di teardown
  (kecuali `KEEP_STACK=1`).
- KM-SYS-001 & KM-SYS-021 & KM-SYS-031 menandai bug path (`/health/live` vs `/live`,
  `QdrantStore`, `/metrics` tanpa auth) sebagai `xfail(strict)` → perbaikannya menutup #13/#9/#14.
- KM-SYS-010/011 adalah bukti inti "survives restarts" yang diklaim `CLAUDE.md` — jangan
  di-skip.
- `psql`/`redis-cli` dijalankan via `docker compose exec postgres ...` supaya tidak perlu
  klien di host.
- Semua assertion HTTP memakai `http://localhost:8000` (port dipetakan compose); untuk WS
  `ws://localhost:8000/ws/voice?token=...`.
