# Rumor Mill AI

A living AI web-toon where characters keep secrets, spread rumors, and continue their lives while you're away.

The MVP's system boundaries, data flow, and non-goals are documented in the
[architecture overview](docs/architecture/README.md). Architectural decisions are recorded as
[ADRs](docs/adr/README.md).

Worlds are defined as validated, versioned JSON. See the
[world-authoring format](docs/world-authoring-format.md) and its minimal fixture.

The first authored world's objective canon and narrative constraints live in the
[Lighthouse story bible](docs/worlds/lighthouse/story-bible.md).
Its mobile-first visitor journeys and launch requirements are defined in the
[Lighthouse MVP experience specification](docs/worlds/lighthouse/mvp-experience.md).

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

## Database migrations

```shell
make db-migrate   # upgrade Postgres to the latest schema
make db-rollback  # roll back one revision
```

The initial migration persists worlds, runs, events, claims, beliefs, memories, scenes,
conversations, jobs, and presentation artifacts. Repository implementations live behind engine
ports so domain code does not import SQLAlchemy.
