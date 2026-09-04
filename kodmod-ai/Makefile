# KODMOD AI — Convenience targets.
# Run `make help` for a list.

PY ?= python
PIP ?= pip
DC ?= docker compose

COMPOSE_TEST ?= docker compose -p kodmod-test -f docker/docker-compose.test.yml

.PHONY: help install install-test dev test lint format seed ingest up down logs migrate clean \
        test-static test-unit test-contract test-integration test-api test-ws test-e2e \
        test-system test-load test-security test-readiness test-ready test-all test-burndown \
        compose-test-up compose-test-up-api compose-test-up-api-perf compose-test-api-down \
        compose-test-down compose-test-logs

help:
	@echo "KODMOD AI — Common targets"
	@echo "  install     Install runtime + dev dependencies"
	@echo "  dev         Run uvicorn with reload"
	@echo "  test        Run pytest"
	@echo "  test-unit   Stage 1 (excludes known_bug)"
	@echo "  test-burndown  Run known_bug tests: FAIL = bug open, PASS = fixed"
	@echo "  lint        Run ruff + mypy"
	@echo "  format      Auto-format with ruff"
	@echo "  seed        Seed sample curriculum"
	@echo "  ingest      Ingest sample documents (data/curriculum/*)"
	@echo "  up          docker compose up (dev)"
	@echo "  down        docker compose down"
	@echo "  logs        Tail api logs"
	@echo "  migrate     Run alembic upgrade head"

install:
	$(PIP) install -e ".[dev]"

install-test:
	$(PIP) install -e ".[test]"

dev:
	$(PY) -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .
	$(PY) -m mypy --ignore-missing-imports agents graphs tools rag api analytics accessibility memory voice config

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

seed:
	$(PY) -m scripts.seed_curriculum

ingest:
	$(PY) -m scripts.ingest_documents --path data/curriculum

up:
	cd docker && $(DC) up -d

down:
	cd docker && $(DC) down

logs:
	cd docker && $(DC) logs -f api

migrate:
	$(PY) -m alembic upgrade head

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +

# ---------------------------------------------------------------- test stages --
# Only the test INFRA runs in Docker (postgres, redis, llm-stub — see
# docker/docker-compose.test.yml). `db-init` (schema+seed via scripts/init_test_db)
# and the `api` server (scripts/serve_test_api) run natively on the host, so a
# code change needs no `docker build`. Test SCRIPTS
# run natively too: `make test-*` below just invokes `python -m pytest`. Stage 4+
# pytest talks to the host `api` over real HTTP/WS on localhost:8000.
# `scripts/run_tests.{ps1,sh}` are the primary entrypoints — they manage the
# host api lifecycle; the `make test-<stage>` targets are for one-shot manual runs
# and leave the server they start running (stop it with `make compose-test-down`).
# Windows: prefer `pwsh scripts/run_tests.ps1` over `bash scripts/run_tests.sh`.
# Ordered pipeline & stage docs: docs/testplan/. run_tests stops at first RED stage.

compose-test-up:
	$(COMPOSE_TEST) up -d postgres redis llm-stub
	$(PY) -m scripts.init_test_db

compose-test-up-api: compose-test-up
	@curl -fsS http://localhost:8000/live >/dev/null 2>&1 || { \
	  mkdir -p reports; \
	  ($(PY) -m scripts.serve_test_api >reports/api.log 2>&1 & echo $$! >reports/.api.pid); }
	@echo "waiting for api on http://localhost:8000/live ..."
	@for i in $$(seq 1 30); do curl -fsS http://localhost:8000/live >/dev/null 2>&1 && exit 0; sleep 2; done; echo "api did not become healthy -- see reports/api.log" >&2; exit 1

compose-test-up-api-perf: compose-test-up compose-test-api-down
	@# Stage 8 needs a *fresh* server: in-memory checkpointer (the Postgres saver
	@# serialises every graph turn on one asyncio.Lock) + reload off.
	@mkdir -p reports
	@KODMOD_CHECKPOINTER=memory SERVE_TEST_API_RELOAD= \
	  sh -c '$(PY) -m scripts.serve_test_api >reports/api.log 2>&1 & echo $$! >reports/.api.pid'
	@echo "waiting for api on http://localhost:8000/live ..."
	@for i in $$(seq 1 30); do curl -fsS http://localhost:8000/live >/dev/null 2>&1 && exit 0; sleep 2; done; echo "api did not become healthy -- see reports/api.log" >&2; exit 1

compose-test-api-down:
	@[ -f reports/.api.pid ] && kill $$(cat reports/.api.pid) 2>/dev/null || true
	@rm -f reports/.api.pid

compose-test-down: compose-test-api-down
	$(COMPOSE_TEST) down -v

compose-test-logs:
	$(COMPOSE_TEST) logs -f

# Each stage gates on REGRESSIONS: `and not known_bug`. Tests tagged
# @pytest.mark.known_bug assert target behaviour of a tracked-but-unfixed bug
# and stay RED until it is fixed. `make test-burndown` shows how many are left.
test-static:
	$(PY) -m pytest -q -m "static and not slow and not known_bug" --junitxml=reports/junit-static.xml

test-unit:
	$(PY) -m pytest -q -m "unit and not known_bug" --cov --cov-report=xml:reports/coverage-unit.xml

test-contract:
	$(PY) -m pytest -q -m "contract and not known_bug"

test-integration: compose-test-up
	$(PY) -m pytest -q -m "integration and not known_bug" --cov --cov-report=xml:reports/coverage-integration.xml

test-api: compose-test-up-api
	$(PY) -m pytest -q -m "api and not known_bug"

test-ws: compose-test-up-api
	$(PY) -m pytest -q -m "ws and not known_bug"

test-e2e: compose-test-up-api
	$(PY) -m pytest -q -m "e2e and not known_bug"

test-system: compose-test-up-api
	$(PY) -m pytest -q -m "system and not known_bug"

test-load: compose-test-up-api-perf
	$(COMPOSE_TEST) --profile load up -d locust
	$(PY) -m pytest -q -m "perf and not known_bug"

test-security: compose-test-up-api
	$(PY) -m pytest -q -m "security and not known_bug"

# Stage 10 repo-inspection meta-checks (no service needed).
test-readiness:
	$(PY) -m pytest -q -m "readiness and not known_bug" --junitxml=reports/junit-readiness.xml

# Known-bug burndown: FAILs = bugs still open, PASSes = fixed (remove the marker).
test-burndown:
	$(PY) -m pytest -q -m known_bug -rN --junitxml=reports/junit-known-bug.xml

test-ready:
	$(PY) -m pytest -q -m "readiness and not known_bug" --junitxml=reports/junit-readiness.xml || true
	$(PY) scripts/readiness_gate.py

# Full ordered run, fail-fast at first RED stage. Windows: use run_tests.ps1.
test-all:
	bash scripts/run_tests.sh
