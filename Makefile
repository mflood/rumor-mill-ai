.PHONY: setup run test lint format ci db-up db-down

setup:
	uv sync --frozen
	uv run pre-commit install

run:
	uv run uvicorn rumor_mill.main:app --reload

test:
	uv run pytest

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
	uv run pytest

db-up:
	docker compose up -d postgres

db-down:
	docker compose down
