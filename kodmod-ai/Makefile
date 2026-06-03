# KODMOD AI — Convenience targets.
# Run `make help` for a list.

PY ?= python
PIP ?= pip
DC ?= docker compose

.PHONY: help install dev test lint format seed ingest up down logs migrate clean

help:
	@echo "KODMOD AI — Common targets"
	@echo "  install     Install runtime + dev dependencies"
	@echo "  dev         Run uvicorn with reload"
	@echo "  test        Run pytest"
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
