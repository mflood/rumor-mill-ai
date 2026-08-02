# Test strategy

The test suite is split into deterministic lanes that can run locally or in CI without model or
network access.

| Lane | Command | Scope |
| --- | --- | --- |
| Unit | `make test-unit` | Domain rules, world loading, providers, narrative logic, and isolated adapters |
| Integration | `make test-integration` | Migrations, repositories, transactions, scheduler, and HTTP API on temporary SQLite databases |
| End to end | `make test-e2e` | Seed, advance time, chat, publish, and return with the same anonymous visitor |
| Parallel | `make test-parallel` | The complete suite distributed across isolated worker processes |
| Full | `make test` | Every default test with 100% statement and branch coverage enforced |

## Production-readiness coverage

- Domain invariants and deterministic propagation are covered by the belief, memory, propagation,
  conversation, recap, and domain-contract suites.
- Persistence and every Alembic revision are upgraded and rolled back in `test_persistence.py`.
  Transaction tests cover explicit rollback, exception rollback, uniqueness, and constraints.
- API, scheduler, durable job idempotency, world validation, and world seeding have dedicated
  integration suites.
- `test_player_can_complete_story_lifecycle_and_return` crosses the deployed application boundary:
  it initializes a seeded world, advances simulation time, establishes a visitor cookie, chats,
  publishes a daily episode, closes the client, and returns with the same identity and history.
- Provider timeout, rate-limit, malformed-output, and safety failures verify that partial turns are
  rolled back and retryability is preserved. Duplicate client message IDs and job idempotency keys
  exercise retry behavior. Multi-tab visitor tests and the parallel lane exercise concurrency and
  state isolation.

The tests use fixed seeds and controlled clocks. Each database-backed test receives a unique path
from pytest's temporary directory, so xdist workers never share SQLite files. The optional Postgres
test requires `RUMOR_MILL_TEST_DATABASE_URL` and should point to an isolated disposable database.
