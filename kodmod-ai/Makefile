# KODMOD AI — Convenience targets.
# Run `make help` for a list.

PY ?= python
PIP ?= pip
DC ?= docker compose

COMPOSE_TEST ?= docker compose -p kodmod-test -f docker/docker-compose.test.yml

.PHONY: help install install-test dev test lint format seed ingest up down logs migrate clean \
        test-static test-unit test-contract test-integration test-api test-ws test-e2e \
        test-system test-load test-security test-ready test-all test-burndown \
        compose-test-up compose-test-down compose-test-logs

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
# kodmod-ai runs entirely in Docker (postgres, redis, llm-stub, api — see
# docker/docker-compose.test.yml). Test SCRIPTS run natively on the host, NOT
# inside a container: `make test-*` below just invokes `python -m pytest`
# directly. Stage 4+ pytest talks to the real `api` container over HTTP/WS.
# Windows: prefer `pwsh scripts/run_tests.ps1` over `bash scripts/run_tests.sh`.
# Ordered pipeline & stage docs: docs/testplan/. run_tests stops at first RED stage.

compose-test-up:
	$(COMPOSE_TEST) up -d postgres redis llm-stub db-init

compose-test-up-api: compose-test-up
	$(COMPOSE_TEST) up -d --build api
	@echo "waiting for api on http://localhost:8000/live ..."
	@for i in $$(seq 1 30); do curl -fsS http://localhost:8000/live >/dev/null 2>&1 && exit 0; sleep 2; done; echo "api did not become healthy" >&2; exit 1

compose-test-down:
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

test-load: compose-test-up-api
	$(COMPOSE_TEST) --profile load up -d --build
	$(PY) -m pytest -q -m "perf and not known_bug"

test-security: compose-test-up-api
	$(PY) -m pytest -q -m "security and not known_bug"

# Known-bug burndown: FAILs = bugs still open, PASSes = fixed (remove the marker).
test-burndown:
	$(PY) -m pytest -q -m known_bug -rN --junitxml=reports/junit-known-bug.xml

test-ready:
	bash scripts/run_tests.sh --gate

# Full ordered run, fail-fast at first RED stage. Windows: use run_tests.ps1.
test-all:
	bash scripts/run_tests.sh
