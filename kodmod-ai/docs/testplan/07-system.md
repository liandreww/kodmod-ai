# Stage 7 — System Test (black-box, infra Docker + api host)

**Tujuan.** Menguji sistem sebagai **kotak hitam**: proses `api` host (`uvicorn api.main:app`
via `scripts/serve_test_api`, membaca source langsung) dijalankan bersama infra Docker
(Postgres+Redis(+Qdrant)), diakses hanya via HTTP/WS. Memverifikasi healthcheck, lifespan
(`init_db` + `AsyncPostgresSaver.setup` + `build_kodmod_graph`), **persistensi state lintas
restart proses `api`**, matriks backend vektor, endpoint operasional (`/metrics`), format
log, dan shutdown anggun.

**Sifat gate.** Blok. 5–10 menit.

**Framework.** `pytest` sebagai driver, dijalankan native di host (PowerShell/bash). Memakai
`httpx` + kontrol proses `api` host lewat pidfile `reports/.api.pid` (SIGTERM + respawn di
fixture `restart_api`) dan `docker` CLI untuk `psql`/`redis-cli` ke kontainer Postgres/Redis.
LLM & embedding proses `api` diarahkan ke service `llm-stub` (`KODMOD_LLM_PROVIDER=vllm` +
`VLLM_BASE_URL=http://localhost:8099/v1`, `KODMOD_EMBED_BACKEND=openai` +
`OPENAI_BASE_URL=http://localhost:8099/v1`) — di-set oleh `scripts/serve_test_api`.

**Entry.** Stage 6 hijau. **Exit.** Semua hijau; persistensi lintas restart terbukti; kedua
backend vektor jalan.

**Lokasi.** `tests/system/`. **Marker.** `system`, `slow`.

**Menjalankan.**
`docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub`
→ `python -m scripts.init_test_db`
→ `python -m scripts.serve_test_api` (atau cukup `pwsh scripts/run_tests.ps1 -Only 7`), lalu
`pytest -m system` native di host. `run_tests` menulis `reports/.api.pid` yang dipakai
fixture restart/shutdown.

---

## Katalog test case

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SYS-001 | Boot & healthy | start `serve_test_api`; poll `GET http://localhost:8000/live` | 200 dalam < 60 s | route `/live` | — |
| KM-SYS-002 | Lifespan sukses | tail `reports/api.log` (stdout uvicorn host) saat start | baris menandakan: `configure_logging`, `init_db` OK (SELECT 1), `AsyncPostgresSaver.setup()` OK, `build_kodmod_graph` OK; tidak ada traceback | `api/main.py` lifespan | — |
| KM-SYS-003 | Checkpoint tables dibuat | `docker compose exec postgres psql` → `\dt` | tabel checkpoint LangGraph (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs` atau setara) ada | `checkpointer.setup()` | — |
| KM-SYS-004 | `GET /ready` end-to-end | curl | 200; `checks.database="ok"`, `checks.redis="ok"` | health handler | — |
| KM-SYS-010 | Persistensi lintas restart proses | (a) `POST /voice/text` `text="halo"` header student, catat `session_id`; (b) `restart_api` (SIGTERM PID + respawn); tunggu healthy; (c) `POST /voice/text` `text="ulangi"` dgn `session_id` sama | respons langkah (c) memakai konteks dari (a) — checkpoint di Postgres (kontainer, tak ikut restart) bertahan; `messages` thread berlanjut | `AsyncPostgresSaver` + `thread_id` | — |
| KM-SYS-011 | Interrupt HITL bertahan restart | jalankan turn yang berhenti di `interrupt_after=["reflection"]`; `restart_api`; resume `thread_id` | turn lanjut ke `accessibility→tts`, tidak mengulang dari awal | compile `interrupt_after` | — |
| KM-SYS-012 | Idempotensi `init_db`/`setup` saat restart | `restart_api` 3× | tidak ada error "table already exists"/"relation exists"; boot tetap < 60 s | idempoten | — |
| KM-SYS-020 | Matriks backend: pgvector (default) | `POST /content/retrieve` setelah ingest | 200, chunk relevan | `VECTOR_BACKEND=pgvector` | — |
| KM-SYS-021 | Matriks backend: qdrant | naikkan profile `qdrant`; restart `serve_test_api` dgn `VECTOR_BACKEND=qdrant`, `QDRANT_URL=http://localhost:6335`; re-ingest; `POST /content/retrieve` | 200, chunk relevan | `rag/stores/qdrant_store.py` — **catat**: `RAGTool` import `QdrantStore` (tak ada) → jalur via `RAGTool` mati; `rag.retriever` pakai fungsi modul → jalur retriever OK. Uji **retriever**, tandai `RAGTool`+qdrant `xfail` | #9 |
| KM-SYS-030 | `/metrics` Prometheus | `GET /metrics` | 200 `text/plain; version=0.0.4`; memuat counter HTTP request; naik setelah beberapa request | `prometheus_client.make_asgi_app` | — |
| KM-SYS-031 | `/metrics` tanpa auth (kontrol) | `GET /metrics` tanpa header | 200 (tidak diproteksi) — dicatat, ditindak KM-SEC-062 | mount | #14 |
| KM-SYS-040 | Format log JSON | `LOG_JSON=true` (default `serve_test_api`); ambil 20 baris `reports/api.log` | tiap baris `json.loads` sukses; ada field level/timestamp/logger | `config.logging._JsonFormatter` (rujukan `docker/log_conf.json`) | — |
| KM-SYS-041 | Log tidak bocor rahasia | grep `reports/api.log` untuk `Bearer `, `JWT_SECRET`, `sk-`, `api_key` | 0 kecocokan | kebijakan | #15 |
| KM-SYS-050 | Shutdown anggun | kirim SIGTERM ke PID `reports/.api.pid` (Windows: `CTRL_BREAK_EVENT`) | exit code 0; log menandakan `checkpointer_cm.__aexit__` + `close_db`; tidak ada koneksi Postgres menggantung (`SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE '%kodmod%'` → 0 setelah beberapa detik) | lifespan shutdown | — |
| KM-SYS-052 | Bootstrap host idempoten | jalankan `python -m scripts.init_test_db` 2× | tidak error (`CREATE TABLE IF NOT EXISTS`, seed idempoten); jumlah baris seed stabil | `create_test_db.py` + `seed_curriculum.py` via `init_test_db` | — |
| KM-SYS-060 | Config `ENV` non-test | `ENV=staging python -m scripts.serve_test_api` (pool aktif, bukan NullPool) | boot OK; `GET /version` `env=staging` | `settings` | — |
| KM-SYS-061 | Reject startup tanpa DB | `serve_test_api` dgn `postgres` dimatikan | `init_db` `SELECT 1` gagal → proses exit non-zero cepat (fail-fast), bukan hang | `init_db` raise | — |
| KM-SYS-062 | Reject startup tanpa checkpointer DB | `LANGGRAPH_DB_URI` menunjuk DB mati | `AsyncPostgresSaver.setup()` gagal → exit non-zero | lifespan | — |

> **Higiene image produksi** (`docker/Dockerfile` non-root & ukuran) pindah ke
> [Stage 0](00-static.md) **KM-STATIC-046/047** — image `docker/Dockerfile` tidak lagi bagian
> dari jalur runtime test.

---

## Catatan implementasi

- Driver `tests/system/conftest.py`: fixture session `compose_stack` hanya memverifikasi
  `GET {API}/live` reachable → `pytest.skip` kalau infra + host api belum jalan. Tidak
  mengelola lifecycle sendiri (itu tugas `scripts/run_tests.{ps1,sh}`).
- `restart_api`: baca `reports/.api.pid`, `os.kill(pid, SIGTERM)` (Windows: `CTRL_BREAK_EVENT`),
  tunggu proses mati, respawn `python -m scripts.serve_test_api`, `wait_healthy()`.
- KM-SYS-021 & KM-SYS-031 menandai bug path (`QdrantStore`, `/metrics` tanpa auth) sebagai
  `xfail(strict)` → perbaikannya menutup #9/#14.
- KM-SYS-010/011 adalah bukti inti "survives restarts" yang diklaim `CLAUDE.md` — jangan
  di-skip. Yang restart adalah **proses `api` host**; Postgres (kontainer) tetap hidup, jadi
  yang diuji murni ketahanan checkpoint di Postgres.
- `psql`/`redis-cli` dijalankan via `docker compose -p kodmod-test -f
  docker/docker-compose.test.yml exec postgres ...` supaya tidak perlu klien di host.
- Semua assertion HTTP memakai `http://localhost:8000`; untuk WS
  `ws://localhost:8000/ws/voice?token=...`.
