# KODMOD AI — Deployment Guide

This document walks through three deployment topologies, ordered by
complexity:

1. **Local dev**           — single-node docker-compose
2. **Single-server prod**  — docker-compose.prod with Caddy + monitoring
3. **Kubernetes**          — sketch of the manifests for scale

---

## 1. Local Dev

```bash
git clone <repo> kodmod-ai && cd kodmod-ai
cp .env.example .env
# fill in ANTHROPIC_API_KEY (or your provider)

cd docker
docker compose up -d            # postgres + redis + api
docker compose logs -f api
```

The first run will:
- create the schema from `database/schema.sql`
- pull faster-whisper large-v3 (~1.5 GB) on first STT call

Seed curriculum + ingest sample docs:

```bash
docker compose exec api python -m scripts.seed_curriculum
docker compose exec api python -m scripts.ingest_documents \
    --path data/curriculum/biology --concept-slug fotosintesis
```

Open `http://localhost:8000/docs` for the OpenAPI UI.

---

## 2. Single-server Prod (small school / pilot)

Hardware target: 1× server with 8 vCPU, 32 GB RAM, 1× NVIDIA L4 (or
similar) GPU for STT/embedder. NVMe SSD ≥ 200 GB.

```bash
cd docker
docker compose -f docker-compose.prod.yml --env-file ../.env up -d
```

Stack:
- 3 replicas of the API container (load-balanced by Caddy).
- PostgreSQL + pgvector (4 GB memory, retention indefinite).
- Redis with LRU cap.
- Caddy (auto HTTPS).
- Prometheus + Grafana.

### TLS / domain

Edit `docker/Caddyfile` and replace `kodmod.example.com`. Caddy will
provision certificates on first request.

### Backups

Schedule `pg_dump` to S3 / object storage:

```bash
docker exec kodmod-postgres pg_dump -U kodmod kodmod | gzip > backup-$(date +%F).sql.gz
```

For RAG-side recoverability, keep the source corpus on object storage
so re-ingestion is always possible — vector data should be considered
**derived**, not primary.

---

## 3. Kubernetes Sketch

```yaml
# api-deployment.yaml (excerpt)
apiVersion: apps/v1
kind: Deployment
metadata: { name: kodmod-api }
spec:
  replicas: 4
  selector: { matchLabels: { app: kodmod-api } }
  template:
    metadata: { labels: { app: kodmod-api } }
    spec:
      containers:
        - name: api
          image: ghcr.io/kodmod/api:0.1.0
          envFrom: [{ secretRef: { name: kodmod-env } }]
          ports: [{ containerPort: 8000 }]
          resources:
            requests: { cpu: "1", memory: "2Gi" }
            limits:   { cpu: "2", memory: "4Gi" }
          readinessProbe:
            httpGet: { path: /health/ready, port: 8000 }
            initialDelaySeconds: 10
          livenessProbe:
            httpGet: { path: /health/live,  port: 8000 }
          volumeMounts:
            - { name: audio, mountPath: /var/lib/kodmod/audio }
      volumes:
        - name: audio
          persistentVolumeClaim: { claimName: kodmod-audio-pvc }
```

Recommended:
- **PostgreSQL**: managed (RDS / Cloud SQL) with pgvector extension enabled.
- **Redis**: managed (ElastiCache / Memorystore) — single shard is fine.
- **Vector store**: scale out by switching `VECTOR_BACKEND=qdrant` and
  pointing at a managed Qdrant cluster.
- **STT GPU pool**: deploy `faster-whisper` workers as a dedicated pool
  with NVIDIA device plugin and a node selector. Use HTTP RPC if the
  pool is separate from the API pods.

### Autoscaling

HPA on CPU + WS connection count (custom metric). API is mostly I/O bound
once warm; CPU saturates under STT bursts. Plan capacity by
**concurrent voice sessions × 1 STT-worker-second per 10 s of audio**.

---

## 4. Operational Runbooks

### Hot rollouts

1. Bump `APP_VERSION` in `config/settings.py`.
2. Push a new image tag.
3. `kubectl rollout restart deployment/kodmod-api` — old pods drain in
   max 30 s (graceful WS close).

### Schema migrations

```bash
alembic revision --autogenerate -m "add column foo"
alembic upgrade head
```

Migrations are idempotent and forward-only by default. For destructive
changes (column drops, type changes), follow a 3-step expand-migrate-contract
pattern across two releases.

### Disaster recovery

- **Lost vector index**: re-ingest from object storage with
  `scripts/ingest_documents.py`.
- **Lost OLTP**: restore latest `pg_dump`. Mastery scores can also be
  re-derived from `quiz_attempts` if necessary
  (see `analytics/student_model.py::StudentModel.recompute_from_history`).
- **Lost Redis**: harmless. Cold start re-fills in seconds.

### Observability checklist

- LangSmith: every session traced with `session_id` tag.
- Prometheus scrape every 15 s; Grafana dashboards in `docker/grafana/`.
- Log shipping: any JSON-aware aggregator (Loki / ELK / Datadog).

---

## 5. Cost Notes (rough order of magnitude)

For 1,000 active students, ~10 sessions/student/week, avg 8 min/session:

| Item                  | Sized for                | Monthly approx. |
|-----------------------|--------------------------|-----------------|
| LLM (mixed Sonnet/Opus, hybrid w/ local 7B for router) | ~250 M tokens | mid 4-figure USD |
| TTS (Piper local)     | bundled in container     | $0 marginal     |
| STT GPU pool          | 1× L4 at 30% utilisation | low 3-figure USD |
| Postgres + pgvector   | 16 GB instance           | low 3-figure USD |
| Redis                 | 1 GB instance            | $20-50          |
| Object storage        | < 100 GB                 | $5-20           |

Use `LLM_*_MODEL` env vars to swap to local models (Llama 3 / Qwen)
when running on-prem and reduce LLM cost to electricity only.
