# Stage 4 — API / Endpoint

**Tujuan.** Menguji seluruh permukaan REST di atas fondasi data yang sudah terbukti:
status code, skema respons, auth matrix, otorisasi (IDOR), validasi input, dan fuzzing
kontrak berbasis OpenAPI.

**Sifat gate.** Blok. 3–6 menit.

**Framework.** `httpx.AsyncClient(base_url="http://localhost:8000")` — **HTTP sungguhan ke
container `api`** yang benar-benar berjalan (image sama dengan produksi, dibangun dari
`docker/Dockerfile`), **bukan** import in-process/`ASGITransport`. Pytest dijalankan native
di host (PowerShell/bash), bukan di dalam kontainer. DB+Redis diakses langsung dari host
untuk seeding data (fixture `student_factory`/`teacher_factory`); LLM/embedding container
`api` di-stub lewat env (`KODMOD_LLM_PROVIDER=vllm` → service `llm-stub`), bukan lewat
`stub_llms`/`stub_embeddings` (fixture itu hanya berlaku untuk Stage 1/3 yang tak melalui
container). `schemathesis` untuk property/contract terhadap `/openapi.json` container.

**Entry.** Stage 3 hijau; stack app naik: `docker compose -p kodmod-test -f
docker/docker-compose.test.yml up -d --build api` (menaikkan seluruh rantai dependency:
postgres → db-init → redis+llm-stub → api) dan `GET /live` sudah 200.
**Exit.** Semua hijau kecuali `xfail(strict)` tercatat (quiz, voice, exercise/generate,
`sub` non-UUID). 0 temuan 5xx dari Schemathesis tanpa `xfail` bertarget.

**Lokasi.** `tests/api/`. **Marker.** `api`, `db`, `redis`.

**Catatan lifespan.** Lifespan (`init_db`, `AsyncPostgresSaver.setup`, `build_kodmod_graph`)
sudah berjalan di dalam container `api` saat proses `uvicorn` start — tidak perlu di-drive
dari test.

---

## 1. Health — `api/routes/health.py` (mount tanpa prefix)

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-001 | `GET /live` | — | 200 `{"status":"alive","ts":<iso>}` | handler | #13 (bukan `/health/live`) |
| KM-API-002 | `GET /ready` sehat | DB+Redis up | 200, `checks.db=true`, `checks.redis=true`, `status` ok | handler | — |
| KM-API-003 | `GET /ready` DB down | matikan koneksi DB (monkeypatch `async_session` raise) | `status="degraded"`, tetap HTTP 200 atau 503 sesuai kode | handler | — |
| KM-API-004 | `GET /ready` Redis down | `get_redis().ping` raise | `checks.redis=false` tapi `status` tidak degraded (Redis non-kritis) | handler | — |
| KM-API-005 | `GET /version` | — | 200, field `{name,version,env,llm_provider,vector_backend,stt_backend,tts_backend}` dari `settings` | handler | — |
| KM-API-006 | Tidak ada `GET /health` | — | 404 | mount tanpa prefix | #13 (dok diperbaiki) |

## 2. Auth matrix — `api/dependencies.py`

Endpoint acuan: `GET /student/me` (butuh `current_student`).

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-010 | Token student valid | header `Authorization: Bearer <student jwt>` | 200 | `_bearer`+`_decode_jwt` | — |
| KM-API-011 | Tanpa header | — | 401 "Missing bearer token" | `_bearer` | — |
| KM-API-012 | Skema salah | `Authorization: Token abc` | 401 | `_bearer` (harus diawali `bearer `) | — |
| KM-API-013 | `sub` bukan UUID | token `sub="not-a-uuid"` | **target 401/422**; saat ini `uuid.UUID(sub)` → `ValueError` → 500 → `xfail(strict)` | handler | #16 |
| KM-API-014 | Token kedaluwarsa | `exp` lampau | 401 "Token expired" | `ExpiredSignatureError` | — |
| KM-API-015 | Secret salah | sign secret lain | 401 "Invalid token" | `PyJWTError` | — |
| KM-API-016 | `alg=none` | token unsigned | 401 | `algorithms=[JWT_ALG]` | — |
| KM-API-017 | Role salah (teacher token ke endpoint student) | teacher jwt → `/student/me` | 403 "Not a student token" | handler | — |
| KM-API-018 | Tanpa klaim `sub` | token `{role:"student"}` | 403 | handler | — |
| KM-API-019 | `sub` valid tapi siswa tak ada | uuid acak | 404 | `session.get(Student)` | — |
| KM-API-020 | Payload di-tamper tanpa re-sign | ubah `role` base64 | 401 (signature invalid) | PyJWT | — |
| KM-API-021 | `current_teacher` mirror | endpoint teacher + student token | 403 "Not a teacher token" | handler | — |

## 3. Inventaris endpoint tanpa-auth

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-030 | Allowlist unauth | untuk tiap rute, cek ada/tidak dependency `current_student`/`current_teacher`; bandingkan dgn allowlist eksplisit | allowlist = `{GET /live, GET /ready, GET /version, GET /openapi.json, GET /docs, GET /redoc}`. Rute lain tanpa auth (`POST /student`, `GET /student/{id}/profile`, semua `/content/*`, `GET /exercise/by-concept/{id}`, `GET /metrics`) → **`xfail(strict)`** (target: butuh auth atau masuk allowlist secara sadar) | keputusan keamanan | #14 |

## 4. Student — `api/routes/student.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-040 | `POST /student` | body `StudentCreate` valid | 201 + `StudentOut`; baris tersimpan | handler | #14 (target: mungkin butuh auth admin) |
| KM-API-041 | `POST /student` invalid | `preferred_language` ilegal | 422 | pydantic | — |
| KM-API-042 | `GET /student/me` | student token | 200 `StudentOut` milik token | handler | — |
| KM-API-043 | `GET /student/{id}/profile` ada | seed siswa+mastery | 200 `StudentProfileOut`; `overall_mastery` = mean; `strong_concepts=[]` (hardcode — dicatat) | handler + `load_profile`+`fetch_weak_concepts(5)` | — |
| KM-API-044 | `GET /student/{id}/profile` tidak ada | uuid acak | 404 | `session.get` | — |
| KM-API-045 | `GET /student/{id}/profile` IDOR | siswa A minta profil siswa B (tanpa auth sama sekali saat ini) | **target**: 403/401 → `xfail(strict)` | keamanan | #14 |

## 5. Content — `api/routes/content.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-050 | `GET /content/concepts` | seed 6 concept | 200 list `ConceptOut` | handler | — |
| KM-API-051 | `... ?subject_id=` | filter | hanya concept subject itu | handler | — |
| KM-API-052 | `GET /content/concepts/{id}` | id valid / acak | 200 / 404 | `session.get` | — |
| KM-API-053 | `GET /content/concepts/{id}/lessons` | seed lessons | 200 list `LessonOut` | handler | — |
| KM-API-054 | `POST /content/retrieve` | body `{query, top_k:5, language:"id"}`, chunk sudah di-ingest | 200 `ContentRetrieveResponse` `{chunks, query}`; ≤ top_k | `rag.retriever.retrieve` (stub embed) | — |
| KM-API-055 | `POST /content/retrieve` `top_k` di luar 1..20 | `top_k=0` / `21` | 422 | pydantic | — |
| KM-API-056 | `POST /content/retrieve` query kosong | `query=""` | 200 `chunks=[]` | `retrieve("")` | — |

## 6. Exercise — `api/routes/exercise.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-060 | `GET /exercise/by-concept/{id}` | seed `Exercise` `is_audio_friendly=True/False` | 200; hanya yang `is_audio_friendly` | handler | — |
| KM-API-061 | `... ` concept tanpa exercise | | 200 `[]` | handler | — |
| KM-API-062 | `POST /exercise/generate` | body `ExerciseGenerateRequest`, `student.id == payload.student_id` | **target** 200 `ExerciseGenerateResponse`; saat ini `ImportError generate_questions_for_student` → modul gagal import → `xfail(strict)` | handler | #7 |
| KM-API-063 | `POST /exercise/generate` IDOR | `payload.student_id` ≠ token | 403 | handler guard | — |

## 7. Quiz — `api/routes/quiz.py`  *(grup `xfail(strict)` sampai #1/#5/#6/#11 beres)*

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-070 | `POST /quiz/start` | body `QuizStartRequest`, student token | **target** 200 `QuizStartResponse` (`quiz_session_id, first_question, total_questions`); saat ini `state["learning_profile"]=student.profile` → `AttributeError` 500 | handler vs model | #1, #5 |
| KM-API-071 | `_load_mastery` | jalur start | **target**: tak error; saat ini `StudentModel.load(id).mastery_scores()` rantai dua coroutine → 500 | kode | #6 |
| KM-API-072 | `POST /quiz/submit` | body `QuizSubmitRequest` (`quiz_session_id, question_id, student_answer`) | **target** 200 `QuizSubmitResponse` (`score, is_correct, feedback, quiz_complete, cumulative_score`); saat ini handler baca `body.session_id`/`body.answer_text` → `AttributeError` | handler vs model | #5 |
| KM-API-073 | `POST /quiz/submit` sesi selesai | jawab soal terakhir | `quiz_complete=True`, `final_summary` terisi | target | #5, #11 |
| KM-API-074 | `POST /quiz/start` IDOR | `body.student_id` ≠ token | 403 | guard (bila ada) / target | #14 |
| KM-API-075 | Response-model validation | FastAPI serialize balik | tidak 500 karena field mismatch | `response_model` | #5 |

## 8. Voice — `api/routes/voice.py`  *(grup `xfail(strict)` sampai #1 beres; text-mode)*

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-080 | `POST /voice/text` | Form `text="jelaskan pecahan"`, student token | **target** 200 `{session_id, response_text, audio_uri}`; `audio_uri=""` (TTS off); saat ini `learning_profile=student.profile` → 500 | handler | #1 |
| KM-API-081 | `POST /voice/text` tanpa text | Form kosong | 422 | FastAPI Form | — |
| KM-API-082 | `POST /voice/chat` content-type bukan audio | upload `text/plain` | 400 (ditolak sebelum proses) | handler check | — |
| KM-API-083 | `POST /voice/chat` audio dummy | upload `audio/wav` byte pendek; STT passthrough (`STT_ENABLED=false` → pakai `user_input`? — jika chat tak sediakan teks, transcript kosong) | **target** 200 dgn `transcript`/`response_text`; saat ini 500 `student.profile` | handler | #1 |
| KM-API-084 | `POST /voice/chat` file kosong | upload 0 byte `audio/wav` | 400/422, bukan 500 | handler | — |

## 9. Analytics — `api/routes/analytics.py`

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-090 | `GET /analytics/student/{id}` self | id == token | 200 `dict` `StudentAggregator.summarise` | handler | — |
| KM-API-091 | `... ` IDOR | id ≠ token | 403 (guard ADA) | handler | — |
| KM-API-092 | `... ?window=` | `today/week/month/all` + invalid `xyz` | 200 sesuai / 422 | `WindowName` Literal | — |
| KM-API-093 | `GET /analytics/student/{id}/spoken` | self | 200 `{spoken, rollup}`; `spoken` string ID | `generate_student_spoken_summary` | — |
| KM-API-094 | `GET /analytics/classroom/{id}` | teacher token | 200 `ClassroomAggregator.summarise` — **butuh `classroom_enrollment`** → `xfail(strict)` | handler | #20 |
| KM-API-095 | `... /alerts` | teacher token | 200 `{alerts, per_student, headline}` → `xfail(strict)` bersama #20 | handler | #20 |
| KM-API-096 | classroom endpoint dgn student token | | 403 "Not a teacher token" | `current_teacher` | — |

## 10. Contract fuzz — Schemathesis

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-100 | Schemathesis semua operation | `schemathesis.from_asgi("/openapi.json", app)`; checks `not_a_server_error`, `status_code_conformance`, `response_schema_conformance`, `content_type_conformance`; `--hypothesis-max-examples=50` | 0 kegagalan; tiap 5xx yang ditemukan → isu + `xfail` bertarget (mis. `sub` non-UUID #16, quiz #5) | OpenAPI | #5, #7, #16 |
| KM-API-101 | Schemathesis auth-required negatif | jalankan tanpa header pada operation ber-auth | semua 401/403, tak ada 500 | — | #16 |
| KM-API-102 | Boundary numerik | `top_k`, `n_questions` di batas & luar batas via hypothesis | 422 konsisten, bukan 500 | pydantic | — |

## 11. Cross-cutting

| ID | Judul | Langkah | Hasil diharapkan | Oracle | Bug ref |
|---|---|---|---|---|---|
| KM-API-110 | CORS preflight | `OPTIONS` dgn `Origin: http://evil.test` | header CORS sesuai `settings.CORS_ALLOW_ORIGINS`; **catat**: `allow_credentials=True` + `allow_origins=["*"]` adalah kombinasi terlarang per spec Fetch → `xfail(strict)` (target: origin eksplisit atau `credentials=False`) | `api/main.py` middleware | — |
| KM-API-111 | 404 handler | path acak | 404 JSON rapi | FastAPI | — |
| KM-API-112 | 405 method salah | `DELETE /student/me` | 405 | FastAPI | — |
| KM-API-113 | Body JSON rusak | `Content-Type: application/json` + `"{"` | 422, bukan 500 | FastAPI | — |
| KM-API-114 | `GET /metrics` | — | 200 text Prometheus; **tanpa auth** (dicatat, ditindak Stage 9) | `make_asgi_app` mount | #14 |

---

## Catatan implementasi

- `student_factory(**overrides)` → insert ORM `Student`, kembalikan `(student, token)` dgn
  `token = jwt.encode({"sub":str(student.id),"role":"student","iat":..,"exp":now+3600}, settings.JWT_SECRET, settings.JWT_ALG)`.
- Untuk endpoint yang menjalankan graph (`/voice/*`, `/quiz/*`): stub LLM autouse membuat
  respons deterministik; assert struktur, bukan isi kalimat.
- Grup `xfail(strict)` di stage ini adalah backlog paling terlihat oleh pengguna — prioritas
  perbaikan setelah Stage 2 kontrak hijau.
- Simpan output Schemathesis ke `reports/schemathesis-api.tap` + `--report`.
