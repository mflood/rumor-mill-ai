# Rumor Mill AI

A living AI web-toon where characters keep secrets, spread rumors, and continue their lives while you're away.

The MVP's system boundaries, data flow, and non-goals are documented in the
[architecture overview](docs/architecture/README.md). Architectural decisions are recorded as
[ADRs](docs/adr/README.md).

The first authored world's objective canon and narrative constraints live in the
[Lighthouse story bible](docs/worlds/lighthouse/story-bible.md).

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker, and Make.

```shell
cp .env.example .env
make setup
make db-up
make run
```

The API is available at <http://127.0.0.1:8000>; `GET /health` returns its health status.

## Development

```shell
make test     # tests with coverage
make lint     # Ruff and mypy
make format   # apply formatting
make ci       # all non-mutating CI checks
make db-down  # stop local Postgres
```
