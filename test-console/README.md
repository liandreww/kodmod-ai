# KODMOD Test Console

A manual test UI for the KODMOD AI backend. **Not for production.** It exists to exercise every
feature by hand and to make the system's interaction with Postgres, Redis, pgvector/Qdrant and the
LangGraph checkpointer visible.

Nothing under `kodmod-ai/` is modified by this app.

## Run

```bash
# 1. backend, from kodmod-ai/
docker compose -p kodmod-test -f docker/docker-compose.test.yml up -d postgres redis llm-stub
python -m scripts.init_test_db
python -m scripts.serve_test_api          # http://localhost:8000, logs to reports/api.log

# 2. console, from test-console/
npm install
cp .env.local.example .env.local          # optional, defaults already match the compose files
npm run dev                               # http://localhost:3100
```

`scripts/serve_test_api` defaults to the Postgres checkpointer. Do **not** set
`KODMOD_CHECKPOINTER=memory` if you want the graph trace page to work — with the in-memory saver
nothing is persisted and the trace is empty (the console says so rather than showing an empty page).

## Profiles

The top bar switches between two backend stacks. Switching clears the session, because the two use
different `JWT_SECRET` values.

| | `test` | `dev` |
|---|---|---|
| Source | `scripts/_testenv.py` | `kodmod-ai/.env`, read at request time |
| Postgres | `localhost:5433/kodmod_test` | whatever `DB_*` says |
| Redis | `localhost:6380` | whatever `REDIS_*` says |
| Qdrant | `localhost:6335` | `QDRANT_URL` |
| JWT secret | `test-secret-not-for-prod-...` | `JWT_SECRET` |
| LLM | stub on `:8099` | real provider |

Secrets are never copied into this folder; `.env.local` holds only localhost DSNs and the dev
profile reads `kodmod-ai/.env` from disk on each request.

## How it talks to the backend

Every REST call goes through `/api/proxy/[...path]` on the Next.js server, not from the browser.
`api/main.py` sets `allow_origins=["*"]` together with `allow_credentials=True`, which browsers
reject on credentialed requests. Proxying also means every request and response is recorded in the
activity timeline. The WebSocket is the one exception — it connects straight from the browser,
because WS handshakes are exempt from CORS.

## Signing in

There is no login endpoint, and neither `students` nor `teachers` has a password column. Signing in
means picking a real row and minting an HS256 token whose `sub` is that row's id, exactly like
`tests/api/conftest.py:47-57`. `POST /student` is unauthenticated, so registering a new student is
the bootstrap path.

The token workbench mints deliberately broken tokens — expired, wrong secret, `alg=none`, unknown
`sub`, wrong role — for the negative paths.

## Seeing the database

`/observe` runs up to four streams into one timeline:

- **Postgres statements** — sets `log_statement='all'` and a `log_line_prefix` carrying the
  application name through `ALTER SYSTEM` + `pg_reload_conf()`, then streams the container log.
  This catches every query the backend runs, including the LangGraph checkpointer, which uses a
  separate psycopg pool that no SQLAlchemy hook could see. `config/logging.py:128` clamps
  `sqlalchemy.engine` to WARNING, so the in-process route is a dead end. Turning the tap off runs
  `ALTER SYSTEM RESET`. If Docker is unreachable it falls back to polling `pg_stat_activity`, which
  only catches slow queries.
- **Redis commands** — a dedicated `MONITOR` connection.
- **api.log** — tails `kodmod-ai/reports/api.log`.
- **Console activity** — every proxied HTTP call, every SQL statement and Redis command the console
  itself ran, every WebSocket frame, and script output.

`/graph` reconstructs the node-by-node execution of a turn from `checkpoints`, `checkpoint_blobs`
and `checkpoint_writes`. Blobs are ormsgpack; `src/lib/msgpack.ts` decodes them including the
LangGraph extension types 0-5, so LangChain messages render as `{__py: "...AIMessage", fields: ...}`
rather than as opaque bytes. Each step shows which node wrote it and a diff against the previous
step.

## Pages

| Path | What it covers |
|---|---|
| `/` | health, dependency status, per-table row counts |
| `/login` | sign in, register, token workbench |
| `/tutor` | `POST /voice/text` and `WS /ws/voice` in text mode, side by side |
| `/quiz` | `POST /quiz/start` and the `/quiz/submit` loop, with the rows it touches |
| `/exercise` | `POST /exercise/generate`, `GET /exercise/by-concept/{id}` |
| `/content` | concepts, lessons, `POST /content/retrieve` |
| `/analytics` | student rollup and spoken summary, classroom rollup and alerts |
| `/voice` | `POST /voice/chat` multipart upload |
| `/graph` | LangGraph checkpoint trace |
| `/observe` | live taps and the unified timeline |
| `/db`, `/db/redis`, `/db/vectors` | datastore explorers with full write access |
| `/admin` | seed scripts, test fixtures, mastery presets, resets |

## Notes about the backend that this UI relies on

These were verified against the source and contradict the checked-in docs:

- `settings.API_PREFIX = "/api/v1"` is never used; every path is at the root. Health is `/live`,
  `/ready`, `/version` — `/health/*` is a 404.
- `POST /voice/chat` and `POST /voice/text` are multipart forms, not JSON.
- The real `/ws/voice` protocol is `{"event":"end_of_speech","transcript":"..."}` in, and
  `partial_transcript` / `token` / `audio_uri` / `final` plus binary audio out. `docs/API.md`
  describes a different, non-existent protocol.
- Auth failures on the WebSocket close with 1008 *before* `accept()`, so the browser sees a failed
  upgrade rather than a close frame.
- `/analytics/*` returns `{"error": ...}` at HTTP 200, and a classroom with an empty roster returns
  a reduced shape with no `students` array.
- `database/schema.sql` is stale; the live schema comes from `database/models.py` plus
  `scripts/create_test_db.py`. The console introspects `information_schema` instead of assuming.
- `interaction_logs` has a column physically named `metadata`, which needs quoting in raw SQL.
