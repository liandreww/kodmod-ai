# Stage 8 — Performance / Load

**Tujuan.** Menetapkan **baseline** dan **ambang regresi** untuk throughput & latency,
menemukan titik jenuh (connection pool, checkpointer write amplification, konkurensi WS),
dan mendeteksi kebocoran lewat soak test.

**Sifat gate.** **Non-blok** untuk rilis awal, tapi **wajib punya baseline tersimpan**.
Regresi > 25 % terhadap baseline → gagal di Stage 10.

**Penting.** LLM = `llm-stub` (respons ~0 ms deterministik). Stage ini mengukur **overhead
framework / graph / DB / checkpointer / serialisasi**, **bukan** latency model. Latency nyata
model di luar lingkup (lihat README §1.2).

**Framework.** `locust` (skenario HTTP/WS), `pytest-benchmark` (micro), `docker stats` /
`psutil` (resource), `psql` (koneksi & lock).

**Entry.** Stage 7 hijau, stack `--profile load` up. **Exit.** Semua skenario menghasilkan
laporan di `docs/testplan/baselines/`; tidak ada kebocoran pada soak 30 menit.

**Lokasi.** `tests/performance/` (`locustfile.py`, `benchmarks/`). **Marker.** `perf`, `slow`.

---

## 1. Skenario beban HTTP (Locust)

Target: `http://api:8000` (dari kontainer `locust`) atau `http://localhost:8000`.

| ID | Skenario | Beban | Metrik & SLO awal (dgn stub) | Bug ref |
|---|---|---|---|---|
| KM-PERF-001 | Tutoring turn | `POST /voice/text` `text` acak dari pool, 1 turn/req; ramp 10→50→100→200 VU, 5 min steady di 50 | p50 < 400 ms, p95 < 1500 ms @ 50 VU; error rate < 1 %; throughput ≥ 40 req/s | #1 (butuh fix agar tidak 500) |
| KM-PERF-002 | Quiz flow | `/quiz/start` → 3× `/quiz/submit` sebagai satu task; 30 VU, 5 min | p95 per-request < 1500 ms; 0 5xx | #5, #11 (xfail sampai beres) |
| KM-PERF-003 | Analytics read | `GET /analytics/student/{id}` (data seeded 30 sesi), 50 VU, 5 min | p95 < 800 ms; hitung query per request (log SQL) → tidak ada N+1 yang meledak dgn ukuran data | — |
| KM-PERF-004 | Content retrieve | `POST /content/retrieve` (stub embed), 50 VU | p95 < 600 ms | — |
| KM-PERF-005 | Campuran realistis | 70% tutoring, 20% analytics, 10% quiz; 100 VU, 10 min | error < 1 %; p95 agregat < 1800 ms; grafik latency stabil (tidak menanjak) | — |

## 2. Titik jenuh & sumber daya

| ID | Judul | Langkah | Hasil diharapkan | Oracle |
|---|---|---|---|---|
| KM-PERF-010 | Saturasi connection pool | naikkan konkurensi bertahap; pantau `pg_stat_activity` & error `QueuePool`/`asyncpg` timeout | laporkan titik knee (VU saat error mulai); `DB_POOL_SIZE=10` + `max_overflow=20` → ~30 koneksi paralel batas teoretis | `database/session.py` |
| KM-PERF-011 | Checkpointer write amplification | 1 turn tutoring = jalur 6 node → ukur jumlah `INSERT` ke tabel checkpoint via `pg_stat_statements` | dokumentasikan write/turn; cari TPS maksimum sebelum lag; bandingkan dengan `checkpointer=None` (turunkan flag di build khusus) | LangGraph checkpoint after every node |
| KM-PERF-012 | Memori kontainer `api` di beban | `docker stats` selama KM-PERF-005 | RSS stabil (naik lalu plateau), tidak monoton naik | — |
| KM-PERF-013 | Redis throughput | beban dgn banyak `append_tutoring_turn`/`set_pacing` | Redis `INFO` ops/sec; latency < 5 ms p99 | `memory/short_term.py` |
| KM-PERF-014 | CPU profil node | jalankan `py-spy dump`/`cProfile` sampel saat beban | node/pemakaian teratas terdokumentasi (kandidat optimasi) | — |

## 3. WebSocket

| ID | Judul | Langkah | Hasil diharapkan | Oracle |
|---|---|---|---|---|
| KM-PERF-020 | Konkurensi `/ws/voice` | 100 koneksi paralel, tiap kirim 1 utterance/10 s selama 5 min (Locust `WebSocketUser` atau skrip `websockets`) | semua koneksi hidup; p95 waktu ke frame `final` < 2 s; tidak ada `1011` | `voice_ws` (butuh #2/#3/#4 fix) |
| KM-PERF-021 | Ramp koneksi | 0→500 koneksi | titik saat `accept` mulai gagal / file descriptor habis | uvicorn 1 worker |

## 4. Soak

| ID | Judul | Langkah | Hasil diharapkan | Oracle |
|---|---|---|---|---|
| KM-PERF-030 | Soak 30 menit | KM-PERF-005 konstan 30 min; snapshot tiap 5 min: `pg_stat_activity` count, Redis clients, RSS `api`, jumlah file di `AUDIO_DIR`/`UPLOAD_DIR` | semua metrik datar (±10 %); tidak ada pertumbuhan koneksi/berkas monoton; error rate tetap < 1 % | kebocoran resource |
| KM-PERF-031 | Recovery pasca-spike | spike 300 VU 60 s lalu turun ke 20 VU | latency kembali ke baseline < 2 min; tidak ada error tersisa | — |

## 5. Micro-benchmark (pytest-benchmark)

| ID | Fungsi | Baseline disimpan sbg | Ambang regresi |
|---|---|---|---|
| KM-PERF-040 | `rag.chunking.chunk_document` (dok 2000 kata) | `baselines/bench.json` | +25 % waktu |
| KM-PERF-041 | `tests/_fakes` stub `embed_text` (batch 16) | idem | +25 % |
| KM-PERF-042 | `agents.scoring_agent._score_mcq` | idem | +25 % |
| KM-PERF-043 | `graphs.main_graph.route_after_intent` | idem | +25 % |
| KM-PERF-044 | `graphs.state.initial_state` | idem | +25 % |
| KM-PERF-045 | `accessibility_agent` fast-path pipeline (teks 800 kata) | idem | +25 % |

Jalankan: `pytest tests/performance/benchmarks -m perf --benchmark-json=docs/testplan/baselines/bench.json`.

---

## Artefak & pelaporan

- `docs/testplan/baselines/locust-<skenario>.json` (`--json`) + `.html` report.
- `docs/testplan/baselines/bench.json` (pytest-benchmark).
- `docs/testplan/baselines/resource-soak.csv` (snapshot `docker stats` + `psql`).
- Ringkasan tren di `08-performance.md` bagian "Hasil terakhir" (diperbarui tiap run
  nightly).

## Catatan implementasi

- `locustfile.py` mendefinisikan `HttpUser` dengan `@task` berbobot + auth (mint JWT sekali
  di `on_start`, seed siswa via `POST /student`).
- CI: Stage 8 **tidak** di PR gate; dijalankan `workflow_dispatch` / nightly, hasil di-commit
  ke `baselines/` oleh job bot atau di-upload sebagai artifact.
- SLO awal adalah *placeholder* untuk lingkungan CI 2 vCPU; angka final ditetapkan setelah
  run baseline pertama dan dicatat di tabel ini.
- Bila #1/#5/#11 belum diperbaiki, KM-PERF-001/002 dijalankan hanya untuk mengukur *error
  path* (semua 500) — tandai `xfail`, aktifkan penuh setelah fitur hijau.
