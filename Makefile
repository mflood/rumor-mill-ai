-include .env

RUMOR_MILL_API_PORT ?= 8787
RUMOR_MILL_POSTGRES_PORT ?= 55432
export RUMOR_MILL_API_PORT RUMOR_MILL_POSTGRES_PORT RUMOR_MILL_DATABASE_URL

.PHONY: setup run test test-unit test-integration test-e2e test-parallel lint format ci eval db-up db-down db-migrate db-rollback seed-lighthouse

setup:
	uv sync --frozen
	uv run pre-commit install

run:
	uv run uvicorn rumor_mill.main:app --reload --port $(RUMOR_MILL_API_PORT)

TEST_DATABASE_URL := sqlite+pysqlite:///:memory:

test:
	RUMOR_MILL_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest

test-unit:
	RUMOR_MILL_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest --no-cov -m "not integration and not e2e and not postgres"

test-integration:
	RUMOR_MILL_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest --no-cov -m "integration and not postgres"

test-e2e:
	RUMOR_MILL_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest --no-cov -m e2e

test-parallel:
	RUMOR_MILL_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -n auto

lint:
	uv run ruff check .
	uv run mypy

format:
	uv run ruff format .
	uv run ruff check --fix .

ci:
	uv lock --check
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	RUMOR_MILL_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest
	$(MAKE) eval

eval:
	uv run python -m rumor_mill.evals evals/lighthouse-v1.json \
		--json-report artifacts/evals/report.json \
		--markdown-report artifacts/evals/report.md

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-migrate:
	uv run alembic upgrade head

db-rollback:
	uv run alembic downgrade -1

seed-lighthouse:
	uv run python -m rumor_mill.worlds.seeding docs/worlds/lighthouse/world.json \
		--database-url $(RUMOR_MILL_DATABASE_URL) --seed 60 \
		--transcript artifacts/lighthouse-smoke-transcript.md
