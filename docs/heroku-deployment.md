# Heroku deployment

Rumor Mill runs as three declared process types:

- `release` applies Alembic migrations before new web and worker code is released.
- `web` serves FastAPI through Uvicorn on Heroku's assigned `$PORT`.
- `worker` advances every running wall-clock simulation from durable Postgres state.

The worker writes a heartbeat on every poll. `/health/live` confirms the web process is alive;
`/health/ready` verifies Postgres, worker freshness, and required provider configuration. A dyno
restart is safe: simulation time and the wall-time anchor are committed in Postgres, catch-up is
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

The smoke check requires liveness, readiness (including a recent worker heartbeat), and a packaged
CSS asset. If release migrations fail, Heroku does not deploy the new release. Inspect the release
log, correct the migration or configuration, and redeploy; never bypass the release phase.

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
