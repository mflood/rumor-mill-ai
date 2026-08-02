# Heroku deployment

Rumor Mill runs as three declared process types:

- `release` applies Alembic migrations and then idempotently bootstraps the validated Lighthouse
  world and a running wall-clock season before new web and worker code is released.
- `web` serves FastAPI through Uvicorn on Heroku's assigned `$PORT`.
- `worker` advances every running wall-clock simulation from durable Postgres state.

The worker writes a heartbeat on every poll. `/health/live` confirms the web process is alive;
`/health/ready` verifies Postgres, worker freshness, and required provider configuration without
depending on story content. `/health/product` separately validates the Lighthouse world and
requires a running season; it returns 503 with a low-cardinality `reason` when play is unavailable.
A dyno restart is safe: simulation time and the wall-time anchor are committed in Postgres, catch-up is
bounded by each run's `max_catch_up_ticks`, and scheduled jobs use unique idempotency keys.

## Provision a fresh app

Install and authenticate the Heroku CLI, then choose a globally unique app name:

```shell
heroku create <app-name>
heroku buildpacks:set heroku/python -a <app-name>
heroku addons:create heroku-postgresql:essential-0 -a <app-name>
heroku config:set \
  RUMOR_MILL_ENVIRONMENT=production \
  RUMOR_MILL_MODEL_PROVIDER=fake \
  RUMOR_MILL_OPERATOR_API_KEY="$(openssl rand -hex 32)" \
  RUMOR_MILL_SECURE_VISITOR_COOKIE=true \
  -a <app-name>
git push heroku main
heroku ps:scale web=1 worker=1 -a <app-name>
```

Heroku's Python buildpack uses `pyproject.toml`, `uv.lock`, and `.python-version`. Heroku Postgres
manages `DATABASE_URL`, including credential rotation; both the app and Alembic release migration
accept and normalize its `postgres://` URL directly while retaining `RUMOR_MILL_DATABASE_URL` as
the explicit local/test override. Do not duplicate the managed URL into another config var, and do
not copy database URLs or API keys into source, logs, review apps, or support messages.

For a real model provider, replace fake mode without exposing the key:

```shell
heroku config:set RUMOR_MILL_MODEL_PROVIDER=openai RUMOR_MILL_OPENAI_API_KEY=<secret> -a <app-name>
```

## Verify and operate

Wait for both dynos to report `up`, then run the repository smoke check:

```shell
heroku ps -a <app-name>
uv run python scripts/smoke_deployment.py https://<app-name>.herokuapp.com
heroku logs --tail -a <app-name>
```

The smoke check requires liveness, infrastructure readiness (including a recent worker heartbeat),
product readiness, and packaged assets. It creates a visitor session, follows the entry redirect to
Today, and opens a linked location or character page. If any playable check fails, the GitHub
deployment job fails; follow the failed-smoke rollback procedure in `ci-cd.md`. If release
migrations fail, Heroku does not deploy the new release. Inspect the release
log, correct the migration or configuration, and redeploy; never bypass the release phase.

Verify bootstrap independently after a release:

```shell
heroku run python -m rumor_mill.bootstrap --database-url "$DATABASE_URL" -a <app-name>
heroku pg:psql -a <app-name> -c "select w.slug, r.status, r.clock_mode from worlds w join runs r on r.world_id=w.id where w.slug='lighthouse';"
curl -i -c /tmp/rumor-mill-cookie -X POST https://<app-name>.herokuapp.com/lighthouse/session
curl -i -b /tmp/rumor-mill-cookie https://<app-name>.herokuapp.com/lighthouse/today
```

The command validates the packaged world before opening a transaction. Re-running it selects the
existing running Lighthouse season; it does not replace world data, visitor state, canon, or a live
run. A validation or database error exits non-zero and therefore fails the release visibly. If it
fails, inspect `heroku logs --tail --ps release`, correct the packaged definition or database
availability, and redeploy. For an already-migrated release, run the same bootstrap command as a
one-off dyno and repeat the verification queries. Never delete a world or run to force recovery.

## Operator console

Visit `https://<app-name>.herokuapp.com/operator` and sign in with the value of
`RUMOR_MILL_OPERATOR_API_KEY`. The single-operator session is stored in a secure, HTTP-only,
same-site cookie and expires after eight hours; sign out from the console when finished. An expired
session redirects to sign-in. Rotate the Heroku config value to immediately invalidate all existing
sessions.

The console separates infrastructure, story availability, worker freshness, and per-run job state.
It lists safe diagnostics only—no private conversation content or secrets. Pause, resume, one-tick
advance, job retry, recap publication, and report review all require a confirmation checkbox and
write the existing append-only operator audit log.

## Rollback and recovery

The full failed-migration, failed-smoke, and rollback procedures are in
[`ci-cd.md`](ci-cd.md). Follow that runbook before changing production data or schema state.

```shell
heroku releases -a <app-name>
heroku rollback <release> -a <app-name>
heroku logs --tail --ps release -a <app-name>
heroku logs --tail --ps worker -a <app-name>
```

Code rollback creates a new release and reruns the current release command. Because database
rollbacks can destroy data expected by newer code, use `alembic downgrade` only after reviewing the
migration and taking a database backup. A stopped worker leaves durable run clocks untouched; when
it returns, capped catch-up prevents an uncontrolled burst.
