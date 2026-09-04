# Stage 9 — Security (dinamis)

**Tujuan.** Menguji keamanan terhadap **sistem yang berjalan**: autentikasi & otorisasi
(JWT, IDOR, privilege escalation), validasi input & injeksi (SQL, SSRF), ketahanan DoS,
kesalahan konfigurasi CORS/headers, dan higiene rahasia saat runtime.

**Kedalaman: Standar.** Tanpa DAST OWASP ZAP. Scan **statis** (bandit, pip-audit, safety,
detect-secrets, Trivy, gitleaks) sudah wajib di [Stage 0](00-static.md).

**Sifat gate.** Blok. 0 temuan High/Critical tanpa *waiver* bertanggal. 3–8 menit.

**Framework.** `pytest` (native di host) + `httpx` terhadap proses `api` host sungguhan
(infra `docker compose ... up -d postgres redis llm-stub` → `python -m scripts.init_test_db`
→ `python -m scripts.serve_test_api`), `PyJWT` untuk
merakit token jahat, `schemathesis` mode negatif/stateful, skrip payload injeksi.

**Entry.** Stage 7 hijau; proses `api` host up dan `/live` 200. **Exit.** Semua kontrol
keamanan hijau kecuali `xfail(strict)` yang tercatat (SSRF guard, rate-limit middleware,
endpoint tanpa-auth) — masing-masing wajib punya isu perbaikan.

**Lokasi.** `tests/security/`. **Marker.** `security`, `slow`.

---

## 1. AuthN / AuthZ

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-001 | JWT tanpa tanda tangan (`alg=none`) | kirim token `{"alg":"none"}` payload `role=student` ke `/student/me` | 401 | `algorithms=[settings.JWT_ALG]` | — |
| KM-SEC-002 | JWT tanda tangan salah | sign HS256 dgn secret `"x"` | 401 | `_decode_jwt` | — |
| KM-SEC-003 | JWT payload di-tamper | ambil token sah, ubah `role`→`teacher` base64 tanpa re-sign, akses endpoint teacher | 401 (signature invalid) | PyJWT | — |
| KM-SEC-004 | JWT `exp` lampau | token kedaluwarsa | 401 "Token expired" | — | — |
| KM-SEC-005 | Tidak ada `aud`/`iss`/`nbf` check | token dgn `aud`/`iss` asing tapi signature & `exp` valid | **saat ini diterima** (tidak divalidasi) → `xfail(strict)` (target: validasi `iss`/`aud` atau dokumentasikan keputusan sadar) | `_decode_jwt` | #16 |
| KM-SEC-006 | `sub` non-UUID → 500 | token `sub="'; DROP"` | **target** 401/422; saat ini `uuid.UUID(sub)` `ValueError` → 500 (bocor stack di DEBUG) → `xfail(strict)` | handler | #16 |
| KM-SEC-007 | Privilege escalation student→teacher | student token ke `GET /analytics/classroom/{id}` | 403 "Not a teacher token" | `current_teacher` | — |
| KM-SEC-008 | IDOR — `/analytics/student/{id}` | student A token, `id` = student B | 403 (guard `student.id != student_id`) | handler guard | — |
| KM-SEC-009 | IDOR — `/analytics/student/{id}/spoken` | idem | 403 | handler | — |
| KM-SEC-010 | IDOR — `/student/{id}/profile` | tanpa/other token, `id` = siswa lain | **target** 401/403; saat ini **tanpa auth** → 200 (bocor profil) → `xfail(strict)` | handler | #14 |
| KM-SEC-011 | IDOR — `/exercise/generate` | `payload.student_id` ≠ token | 403 | handler guard | — |
| KM-SEC-012 | IDOR — `/quiz/*` | `student_id`/`session_id` milik siswa lain | **target** 403; verifikasi setelah #5 fix | handler | #5, #14 |
| KM-SEC-013 | Endpoint tanpa-auth inventory (kontrol keamanan) | jalankan ulang KM-API-030 sebagai gate keamanan | hanya allowlist yang tanpa auth; sisanya `xfail(strict)` | keputusan | #14 |
| KM-SEC-014 | `JWT_SECRET` default lemah | assert `settings.JWT_SECRET != "change-me-in-production"` di image `api` | **target** pass; bila image test pakai default → gagal (harus di-set via env) | `config/settings.py` + `.env.example` | #15 |
| KM-SEC-015 | Brute-force / lockout | 50 request dgn token acak invalid | semua 401; tidak ada info timing yang membocorkan validitas `sub` | — | — |

## 2. Injeksi SQL (jalur raw SQL)

Target modul dgn SQL string / `text()`: `analytics/student_model.py` (`load`/`persist`),
`analytics/aggregator.py` (`ClassroomAggregator` roster), `rag/stores/pgvector_store.py`
(`_vec_literal`, `CAST`), filter `concept_id`/`language`.

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-020 | `student_id` payload injeksi via API | `GET /analytics/student/{id}` dgn `id = "00000000-0000-0000-0000-000000000000' OR '1'='1"` | 422 (bukan UUID) — path parser menolak sebelum SQL | FastAPI UUID converter | — |
| KM-SEC-021 | `concept_id` filter injeksi | `POST /content/retrieve` body / `GET /exercise/by-concept/{id}` dgn payload SQL | 422 / 400; query tetap parameterized; 0 baris bocor | pgvector_store `query` | — |
| KM-SEC-022 | `language` param injeksi | `POST /content/retrieve` `language="id'; DROP TABLE curriculum_chunks;--"` | ditangani sebagai literal (parameter bind); tabel utuh setelahnya | store `query` | — |
| KM-SEC-023 | `source` di ingestion | ingest dokumen dgn `source` berisi payload | tersimpan literal; `delete_by_source` aman | store | — |
| KM-SEC-024 | `StudentModel.load` `:sid` | panggil node dgn `student_id` string aneh (via graph state) | `CAST(:sid AS uuid)` → error UUID ditangani, bukan injeksi | `student_model.load` | — |
| KM-SEC-025 | Verifikasi binding, bukan f-string | audit statis (pytest membaca sumber) semua `text(...)` / `execute(...)` di modul di atas | tidak ada `%`/f-string/`+` untuk menyisipkan nilai user ke SQL; `_vec_literal` hanya angka | grep AST | — |
| KM-SEC-026 | `ClassroomAggregator` roster raw | `GET /analytics/classroom/{id}` dgn `id` UUID acak + (setelah #20) payload | parameterized; 0 kebocoran | aggregator | #20 |

## 3. SSRF / fetch tak tepercaya

`voice/streaming.py` `_ensure_local`/`fetch_audio` menerima `http(s)://`, `s3://`,
`minio://` dari `audio_input_path` / upload.

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-030 | SSRF metadata cloud | kirim state / request dgn `audio_input_path="http://169.254.169.254/latest/meta-data/"` | **target**: ditolak (allowlist skema/host, blok IP link-local/private). Saat ini tidak ada guard → `xfail(strict)` | `_ensure_local` | — |
| KM-SEC-031 | SSRF localhost | `audio_input_path="http://localhost:8000/metrics"` | ditolak → `xfail(strict)` | idem | — |
| KM-SEC-032 | SSRF DNS internal | host `.internal` / private RFC1918 | ditolak → `xfail(strict)` | idem | — |
| KM-SEC-033 | Path traversal lokal | `audio_input_path="../../etc/passwd"` | ditolak / dinormalisasi ke `UPLOAD_DIR` | `_ensure_local` | — |
| KM-SEC-034 | Skema tak diizinkan | `file://`, `gopher://` | ditolak | idem | — |

## 4. DoS / batas sumber daya

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-040 | Body JSON raksasa | `POST /content/retrieve` body 50 MB | 413/400 cepat, bukan OOM | FastAPI/uvicorn limit | — |
| KM-SEC-041 | Upload audio melebihi batas | `POST /voice/chat` file > ukuran wajar / durasi > `MAX_AUDIO_SECONDS` (120) | ditolak 413/400 | `MAX_AUDIO_SECONDS` + `save_upload` | — |
| KM-SEC-042 | WS frame PCM sangat besar | satu `bytes` 20 MB ke `/ws/voice` | ditangani/ditolak, tidak OOM | `_collect_utterance` | — |
| KM-SEC-043 | WS utterance tak berujung | kirim PCM terus tanpa `end_of_speech` | ada batas waktu/ukuran akumulasi; koneksi ditutup wajar | `_collect_utterance` — **target**; kini tak berbatas → `xfail(strict)` | — |
| KM-SEC-044 | Banyak koneksi WS | 300 koneksi cepat | server tetap responsif untuk `/live`; degradasi anggun | uvicorn | — |
| KM-SEC-045 | Slow headers (slowloris ringan) | 50 koneksi kirim header 1 byte/detik | timeout terpasang; worker tidak habis | uvicorn timeout | — |
| KM-SEC-046 | Rate limiting hilang | 500 request/menit dari 1 token ke `/voice/text` | **target**: 429 setelah ambang (middleware `api/middleware/rate_limit.py`). File tsb **tidak ada** → `xfail(strict)` (isu: implementasi rate limit) | referensi di `voice_stream.py` | — |
| KM-SEC-047 | Graph recursion / loop | input yang memicu router bolak-balik | `recursion_limit` LangGraph memutus; 1 request tidak menggantung selamanya | compile config | — |

## 5. Schemathesis negatif / stateful

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-050 | Fuzz 5xx & type confusion | `schemathesis` `--checks all`, stateful, `--hypothesis-max-examples=200`, header auth diinjeksi | 0 respons 5xx tanpa `xfail` bertarget; tidak ada content-type mismatch; tidak ada echo payload berbahaya di error | OpenAPI | #5, #16 |
| KM-SEC-051 | Header injection | payload `\r\n` di field yang mungkin masuk header/log | tidak ada CRLF split di respons/log | — | — |

## 6. CORS / headers

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-060 | CORS `*` + credentials | preflight `Origin: http://evil.test` | **target**: tidak mengembalikan `Access-Control-Allow-Credentials: true` bersama `Allow-Origin: *` (kombinasi terlarang). Saat ini middleware set `allow_credentials=True` + `origins=["*"]` → `xfail(strict)` | `api/main.py` | — |
| KM-SEC-061 | Security headers | `GET /live` | catat ketiadaan `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, HSTS (di belakang Caddy di prod) → rekomendasi, `xfail` bila jadi kebijakan | — | — |
| KM-SEC-062 | `/metrics` terekspos | `GET /metrics` tanpa auth dari origin luar | **target**: diproteksi (token/ jaringan internal). Kini publik → `xfail(strict)` | mount `/metrics` | #14 |
| KM-SEC-063 | Error verbosity | picu 500 dgn `DEBUG=false` | body error generik, tanpa traceback/SQL | FastAPI exception handler + `settings.DEBUG` | — |

## 7. Higiene rahasia runtime

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-SEC-070 | Rahasia tidak ter-log | jalankan beban Stage 6–9, grep seluruh log kontainer | 0 kemunculan `Bearer <...>`, `sk-`, `sk-ant-`, nilai `JWT_SECRET`, `OPENAI_API_KEY` | kebijakan | #15 |
| KM-SEC-071 | Rahasia tidak di respons | inspeksi body `/version`, `/ready`, error | tidak mengembalikan key/secret; `/version` hanya nama provider | handler | — |
| KM-SEC-072 | `.env` tidak masuk image | `docker run kodmod-api:test cat /app/.env` | tidak ada / bukan berisi rahasia asli | `.dockerignore` | #15 |

---

## Catatan implementasi

- `tests/security/_jwt_attacks.py`: helper merakit token (`alg=none`, tamper, kadaluarsa,
  `aud` asing, `sub` non-UUID).
- Setiap `xfail(strict)` di sini **wajib** punya baris di `traceability.md` dengan ID isu
  perbaikan (SSRF guard, rate-limit middleware, proteksi `/metrics`, auth `/student/{id}/profile`,
  CORS credentials, `iss/aud` validation).
- Gate Stage 9: skrip menghitung temuan bertingkat; `High/Critical` tanpa waiver bertanggal
  di `.security-waivers.yml` → exit non-zero.
- DAST ZAP **tidak** dijalankan (kedalaman Standar); bila kelak dinaikkan ke "Dalam", tambah
  `tests/security/zap_baseline.sh` + service `zap` profile `security`.
