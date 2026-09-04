# Stage 0 — Static & Build Gates

**Tujuan.** Menangkap kelas bug yang membuat *seluruh* pipeline gagal sebelum satu test pun
jalan: import mati, `SettingsError` dari `.env`, ketidakcocokan tipe, kerentanan dependensi,
rahasia ter-commit, image tidak bisa dibangun.

**Sifat gate.** Blok total. Tidak ada stage lain dijalankan bila Stage 0 merah.

**Framework / alat.** `ruff` (lint + format + rule set `S`), `mypy`, `bandit`, `pip-audit`,
`safety`, `detect-secrets`, skrip shell, `docker compose config`, `docker build`.
Di CI ditambah `gitleaks` action + `trivy fs`/`trivy image`.

**Entry.** Repo checkout bersih; `pip install -e ".[test]"` sukses (Python 3.11).
**Exit.** Semua perintah exit 0; 0 temuan `bandit` severity HIGH; 0 CVE HIGH/CRITICAL tanpa
*waiver* bertanggal; image `docker/Dockerfile` (backend) & `docker/llm_stub/Dockerfile`
terbangun. Semua perintah stage ini jalan native di host — tidak ada yang jalan di dalam
kontainer.

**Menjalankan.** Seluruh stage ini adalah satu run `pytest -m static` atas `tests/static/`
(setiap kasus men-*shell-out* ke ruff/mypy/bandit/pip-audit/detect-secrets/`docker compose`
dan otomatis `skip` bila alat tak terpasang). `make test-static` dan
`scripts/run_tests.{sh,ps1} --only 0` menjalankan `pytest -q -m "static and not slow"`;
CI menjalankan `-m static` penuh (runner punya Docker → kasus build image ikut).
Bagian statis boleh paralel dengan Stage 1–2 di CI (tidak saling bergantung).

---

## Katalog test case

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref | Marker |
|---|---|---|---|---|---|---|
| KM-STATIC-001 | Lint bersih | `ruff check .` (select `E,F,I,N,UP,B,A,C4,RUF,S`) | exit 0 | ruff config | — | static |
| KM-STATIC-002 | Format konsisten | `ruff format --check .` | exit 0 | ruff format | — | static |
| KM-STATIC-003 | Type check inti | `mypy --ignore-missing-imports agents graphs tools rag api analytics accessibility memory voice config` | exit 0 | mypy | #1,2,4,5,6,7 | static, **known_bug** (62 error mypy) |
| KM-STATIC-004 | Type check `tests/` (bertahap) | `mypy tests` | exit 0 | mypy | — | static, **known_bug** (utang tipe tests/) |
| KM-STATIC-010 | Import-smoke tiap paket | `python -c "import agents, graphs, tools, rag, api, analytics, accessibility, memory, voice, config, database, models"` | tidak ada `ImportError`/`ModuleNotFoundError` | Python import | bug 1, #7, #9 | static *(hijau sekarang; `known_bug` per-modul via `KNOWN_DEAD` bila regresi)* |
| KM-STATIC-011 | Import tiap submodul agen & route | loop `importlib.import_module` atas semua `*.py` di `agents/`, `api/routes/`, `api/websockets/`, `rag/`, `analytics/`, `accessibility/`, `voice/`, `memory/` | semua sukses | Python import | bug 1, #7, #9, #19 | static *(hijau sekarang; `KNOWN_DEAD`→`known_bug` bila regresi)* |
| KM-STATIC-012 | Settings load — env bersih | subprocess dengan `env` minimal (hanya `PATH`), `python -c "from config.settings import settings; print(settings.ENV)"` | exit 0, cetak `dev` | pydantic-settings | L-16 | static |
| KM-STATIC-013 | Settings load — `.env.example` | salin `.env.example`→`.env` di dir sementara, import `settings` | exit 0, tidak `SettingsError` (`CORS_ALLOW_ORIGINS=*` tidak di-JSON-decode) | pydantic-settings + `enable_decoding=False` | L-16 | static |
| KM-STATIC-014 | Settings load — provider openai | `KODMOD_LLM_PROVIDER=openai` + `OPENAI_API_KEY=x`, import `settings` & `tools.llm_client` | exit 0 | settings | — | static |
| KM-STATIC-015 | Properti DSN | assert `settings.DATABASE_URL` diawali `postgresql+asyncpg://`, `settings.LANGGRAPH_DB_URI` diawali `postgresql://` (tanpa `+asyncpg`) | string persis | `config/settings.py` | — | static |
| KM-STATIC-020 | SAST bandit | `bandit -r agents graphs tools rag api analytics accessibility memory voice config database scripts -f json` | 0 isu `severity=HIGH` | bandit | — | static |
| KM-STATIC-021 | Secret scan | `detect-secrets scan --baseline .secrets.baseline` | 0 secret baru; entri `.env` on-disk ada di baseline dengan komentar *"ROTATE — tracked in ISSUE-xxx"* | detect-secrets | #15 | static |
| KM-STATIC-022 | Tidak ada rahasia di tracked files | `git ls-files` → grep pola `sk-`, `sk-ant-`, 64-hex `JWT_SECRET` | tidak ada match di file ter-track (`.env` gitignored) | regex | #15 | static |
| KM-STATIC-030 | Dependency CVE (pip-audit) | `pip-audit -f json` | 0 vuln HIGH/CRITICAL tanpa waiver di `.pip-audit-ignore` | OSV / PyPA advisory | — | static |
| KM-STATIC-031 | Dependency CVE (safety) | `safety check --json` | idem, sebagai *cross-check* | Safety DB | — | static |
| KM-STATIC-032 | Dependensi backend opsional | assert paket untuk backend non-default (`langchain-ollama`, `openai`, `deepgram-sdk`, `piper`, `azure-*`, `elevenlabs`, `TTS`) **tidak** diperlukan di jalur text-mode; test mendokumentasikan mana yang absen | import guard | — | static |
| KM-STATIC-040 | Compose test valid | `docker compose -p kodmod-test -f docker/docker-compose.test.yml config -q` | exit 0; service = `postgres`, `redis`, `qdrant` (profile), `llm-stub`, `locust` (profile) — **tidak ada** `db-init`/`api` (jalan di host) | compose schema | — | static |
| KM-STATIC-041 | Compose test — profile | `... --profile load config -q`, `... --profile qdrant config -q` | exit 0 semua | compose | — | static |
| KM-STATIC-042 | Build image app (produksi) | `docker build -f docker/Dockerfile -t kodmod-api:test ..` | sukses; `EXPOSE 8000`; user non-root `kodmod` — regresi image produksi (bukan jalur test runtime; test pakai `scripts/serve_test_api` di host) | Dockerfile | — | static, slow |
| KM-STATIC-044 | Build image llm-stub | `docker build -f docker/llm_stub/Dockerfile -t kodmod-llmstub:test docker/llm_stub` | sukses; `/health` 200 saat `docker run` | llm_stub | — | static, slow |
| KM-STATIC-046 | Image produksi non-root & minim | `docker inspect` / `docker run kodmod-api:test whoami` | user `kodmod` (uid 1001); `ffmpeg`/`libsndfile1` ada; tidak ada toolchain build di runtime stage | `docker/Dockerfile` (dipindah dari KM-SYS-070) | — | static, slow |
| KM-STATIC-047 | Ukuran & layer image produksi | `docker image inspect kodmod-api:test` | ukuran wajar (< ~1.5 GB tanpa torch/model); catat baseline | Dockerfile multi-stage (dipindah dari KM-SYS-071) | — | static, slow |
| KM-STATIC-045 | Pytest & tooling ada di host | `python -m pytest --version`, `ruff --version`, `mypy --version` di shell host (PowerShell/bash) | semua ada — pengujian TIDAK butuh image test-runner terpisah | `pip install -e ".[test]"` | — | static |
| KM-STATIC-050 | Marker terdaftar | `pytest --markers` | semua marker kustom muncul; `pytest -q` tidak memunculkan `PytestUnknownMarkWarning` | pyproject `[tool.pytest.ini_options].markers` | — | static |
| KM-STATIC-051 | Koleksi bersih | `pytest --collect-only -q` | 0 error koleksi di seluruh `tests/` | pytest | #18 | static |
| KM-STATIC-052 | `requirements.txt` ⇔ `pyproject` inti | diff daftar dependensi inti | identik (atau perbedaan ter-dokumentasi) | kedua file | — | static |
| KM-STATIC-060 | Alembic konsisten | `alembic check` (atau: dokumentasikan `database/migrations/versions/` kosong → bootstrap via `create_test_db`) | tidak ada drift tak terduga | alembic env | — | static, **known_bug** (`versions/` kosong) |

---

## Catatan implementasi

- **KM-STATIC-010/011** ditulis sebagai test pytest (`tests/static/test_imports.py`) memakai
  `importlib`. Modul yang diketahui mati masuk `KNOWN_DEAD` dan ditandai
  `@pytest.mark.known_bug` (asersi biasa → MERAH sampai dead import dihapus, lalu hijau
  sendiri; tak ada `xfail`/`xpass`). `KNOWN_DEAD` **kosong sekarang** — ketiga modul
  (`agents/tutoring_agent.py`, `api/routes/exercise.py`, `tools/rag_tool.py`) sudah
  meng-*import* bersih; #7/#9 masih bawa bug lebih dalam yang ditangkap mypy/contract.
- **KM-STATIC-012..015** dijalankan lewat `subprocess` dengan `env=` terkontrol supaya
  singleton `settings` (di-`lru_cache` saat import) tidak tercemar proses pytest.
- `.secrets.baseline` di-generate sekali (`detect-secrets scan > .secrets.baseline`),
  entri `.env` diberi `# pragma: allowlist secret` + referensi isu rotasi.
- `ruff` `select` ditambah `"S"`; `[tool.ruff.lint.per-file-ignores]` `"tests/**" = ["S101"]`
  (assert diperbolehkan di test), `"scripts/**" = ["S603","S607"]` bila perlu.
- CI job `static` juga menjalankan `gitleaks detect` dan `trivy image kodmod-api:test`
  (fail on `--severity HIGH,CRITICAL`); hasil di `reports/`.
