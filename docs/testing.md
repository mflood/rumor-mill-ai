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

## Lighthouse navigation and lifecycle contract

The canonical product behavior is the Lighthouse experience specification's
[navigation and season lifecycle contract](worlds/lighthouse/mvp-experience.md#navigation-and-season-lifecycle-contract).
Navigation assertions are deterministic release requirements, not substitutes for manual visual
review. Coverage must be assigned as follows:

| Test layer | Required deterministic assertions |
| --- | --- |
| Unit | The shared navigation policy produces **Today · Town · Archive** before entry and **Today · Town · People · Archive** for an entered active visit; route-to-section mapping selects exactly one current destination; visibility is independent of public presence, private reachability, encounter count, and episode count; player-facing labels never expose internal run IDs or run terminology. |
| Integration | Server-rendered Today, Town/location, People/profile, contact/conversation, Archive/episode, and their empty, quiet, stale, and error variants contain the exact ordered labels and season-scoped hrefs, with one correct `aria-current="page"`. The lifecycle matrix covers pre-entry, active with publications, active with zero publications, quiet/no-presence, paused, completed, between seasons with history, and between seasons without history. Archive access and empty states remain public; People remains visitor-scoped; cross-visitor and malformed-season requests fail safely; navigation reads do not mutate simulation, read markers, visitor notes, or conversations. |
| End to end | A new visitor enters, moves through all four destinations without JavaScript, follows Town → person → profile/conversation and People → profile paths, returns to Archive, and preserves the same visitor and selected season. A returning visitor can read their own paused/completed ledger and published history without gaining contact actions or seeing another visitor's data. |
| Deployment smoke | Over HTTPS, the public landing exposes Archive but not People before entry; a seeded entered visit renders all four ordered destinations; Archive returns a truthful HTTP 200 empty or published state; links resolve without raw IDs in visible text; keyboard traversal, the accessible navigation name, `aria-current`, 320 CSS pixel layout, and 200% zoom receive release evidence. Smoke checks verify routing and rendered semantics only, not hidden story state. |

The unit and integration lanes own exhaustive state combinations. End-to-end coverage proves the
journey and isolation boundaries, while deployment smoke catches production routing, asset, and
responsive regressions. A manual launch pass may supplement these lanes but must not be the only
evidence for navigation order, lifecycle access, spoiler safety, or visitor isolation.
