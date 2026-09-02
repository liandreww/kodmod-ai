# Stage 10 — Release Readiness Gate

**Tujuan.** Gerbang tunggal yang memutuskan sistem **"siap dipakai"**. Bukan test baru —
melainkan agregasi bukti dari Stage 0–9 + kebijakan ambang.

**Sifat gate.** Gate rilis. Dijalankan setelah semua stage lain.

**Menjalankan.** `make test-ready` → `scripts/run_tests.sh --gate` (menghitung metrik dari
`reports/` + `docs/testplan/baselines/`).

---

## Kriteria

| ID | Kriteria | Ambang | Sumber |
|---|---|---|---|
| KM-READY-001 | Coverage modul logika murni | ≥ 90 % baris | `coverage combine` Stage 1–3, filter paket `analytics`, `rag/chunking`, `accessibility`, `graphs` |
| KM-READY-002 | Coverage keseluruhan | ≥ 75 % baris | `coverage combine` semua stage pytest |
| KM-READY-003 | **Bug burndown** | `pytest -m known_bug` (via `make test-burndown`): 0 `failed` untuk bug *target-rilis*, lalu penanda `@pytest.mark.known_bug` dihapus (0 test `known_bug` tersisa di suite rilis) | `reports/junit-known-bug.xml` → `reports/burndown.md` |
| KM-READY-004 | Stage 0–7 & 9 | `-m "<marker> and not known_bug"` hijau semua (0 `failed`, 0 `error`) | junit |
| KM-READY-005 | Regresi performa | Tiap metrik KM-PERF-001..005, -040..045 dalam **±25 %** baseline; tidak ada tren menanjak pada soak | `baselines/*.json` |
| KM-READY-006 | Kebocoran soak | Koneksi PG/Redis, RSS, jumlah berkas datar selama 30 min (±10 %) | `baselines/resource-soak.csv` |
| KM-READY-007 | Temuan keamanan | 0 `High`/`Critical` tanpa *waiver* bertanggal di `.security-waivers.yml` | Stage 0 (bandit/pip-audit/safety/trivy/gitleaks) + Stage 9 |
| KM-READY-008 | Rahasia | `.env` on-disk **dirotasi** (isu ditutup); tidak ada rahasia di file ter-track / image / log | KM-STATIC-021/022, KM-SYS-041, KM-SEC-070..072 |
| KM-READY-009 | Traceability lengkap | 0 baris di `traceability.md` tanpa ≥ 1 Test ID; setiap `L-1..L-16` & temuan `#1..#20` terpetakan | `traceability.md` linter |
| KM-READY-010 | Order-independence | `pytest -p randomly -n auto -m "not slow and not perf"` hijau 3× berturut dgn seed acak | pytest-randomly |
| KM-READY-011 | Dokumen sinkron | `docs/API.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md` diperbarui utk path health (`/live`), status quiz, backend qdrant, endpoint auth | review manual + checklist |
| KM-READY-012 | Migrasi | Ada jalur migrasi resmi (alembic `versions/` terisi **atau** keputusan sadar "schema dari ORM `create_all`" terdokumentasi) | `database/migrations/` |

---

## Definition of Done — daftar bug yang test `known_bug`-nya harus HIJAU (lalu penanda dicabut) sebelum rilis

Dari [`traceability.md`](traceability.md), kelompok *target-rilis*:

| Bug | Test kunci | Stage |
|---|---|---|
| Dead imports (`StudentProfileTool`, `generate_questions_for_student`, `QdrantStore`) | KM-STATIC-010/011, KM-CONTRACT-028 | 0, 2 |
| `init_db` `text("SELECT 1")` | KM-INT-001 | 3 |
| Graph: `mini_quiz` orphan + jalur skoring unreachable | KM-CONTRACT-032, KM-INT-150..154, KM-E2E-002 | 2, 3, 6 |
| `Student.profile` (voice/quiz/ws) | KM-API-070/080, KM-WS-014, KM-E2E-001 | 4, 5, 6 |
| `Student.language` di WS | KM-WS-013 | 5 |
| `StreamingSTT.feed()` dict vs tuple | KM-WS-011 | 5 |
| `stream_tts` signature/iterasi | KM-WS-012 | 5 |
| Quiz request/response field mismatch | KM-CONTRACT-020/021, KM-API-072 | 2, 4 |
| `_load_mastery` chain coroutine | KM-CONTRACT-022, KM-API-071 | 2, 4 |
| `/exercise/generate` missing symbol | KM-API-062 | 4 |
| LLM getter dipanggil dgn argumen (#8) — ✅ **FIXED** Stage 1 | KM-UNIT-123/133, KM-INT-115 | 1, 3 |
| `route_after_scoring` hardcode 0.6 (#12) — ✅ **FIXED** Stage 1 | KM-UNIT-063 | 1 |
| `sub` non-UUID → 500 | KM-API-013, KM-SEC-006 | 4, 9 |
| Endpoint tanpa-auth (`/student/{id}/profile`, `/metrics`, ...) | KM-API-030, KM-SEC-010/013/062 | 4, 9 |
| `rag_retrieval_node` baca `concept_id` + isi `next_action` | KM-CONTRACT-037/038, KM-INT-091 | 2, 3 |
| SSRF guard di `_ensure_local` | KM-SEC-030..034 | 9 |
| Rate-limit middleware | KM-SEC-046 | 9 |
| CORS credentials + `*` | KM-API-110, KM-SEC-060 | 4, 9 |
| Healthcheck path `/health/live` vs `/live` | KM-SYS-001 | 7 |
| `classroom_enrollment` bukan ORM | KM-INT-078, KM-API-094/095, KM-E2E-004 | 3, 4, 6 |
| `CORS_ALLOW_ORIGINS` decoding (L-16) | KM-STATIC-013 | 0 |
| WS `StreamingSTT` tak menghormati `STT_ENABLED` (#21, ditemukan saat mendesain pengujian black-box) | KM-WS-010, KM-WS-030, KM-WS-041 | 5 |

*Boleh tetap MERAH / `known_bug` (bukan blocker rilis, keputusan sadar & terdokumentasi —
atau: hapus test-nya bila memutuskan tak akan diperbaiki):* dukungan header `Authorization`
di WS (#17), frame WS `agent_event`/`audio_chunk` biner, `strong_concepts` hardcode `[]` di
profil, `schema.sql` (di-*deprecate*, bukan diperbaiki).

---

## Output

`reports/readiness.md` — tabel kriteria KM-READY-001..012 dengan status PASS/FAIL + nilai
terukur, di-generate `scripts/run_tests.sh --gate`. Rilis di-ACC hanya bila **semua PASS**.
