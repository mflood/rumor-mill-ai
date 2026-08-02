# Heroku deployment

Rumor Mill runs as three declared process types:

- `release` applies Alembic migrations and then idempotently bootstraps the validated Lighthouse
  world and a running wall-clock season before new web and worker code is released.
- `web` serves FastAPI through Uvicorn on Heroku's assigned `$PORT`.
- `worker` advances every running wall-clock simulation from durable Postgres state.

The worker writes a heartbeat on every poll. `/health/live` confirms the web process is alive;
`/health/ready` verifies Postgres, worker freshness, autonomous story-pipeline composition, and
required provider configuration without depending on story content. `/health/product` separately
validates the Lighthouse world and requires a running season; it returns 503 with a low-cardinality
`reason` when play is unavailable.
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
  RUMOR_MILL_METRICS_API_KEY="$(openssl rand -hex 32)" \
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

The smoke check requires liveness, infrastructure readiness, a recent autonomous clock-progress
signal, product readiness, and packaged assets. It only reads persisted pipeline telemetry and
public pages; it never enqueues work or invokes a model provider, so it cannot create a paid call.
It creates a visitor session, follows the entry redirect to Today, and opens a linked location or
character page. If any playable check fails, the GitHub
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

## Metrics monitoring

Production `/metrics` requests require the dedicated `RUMOR_MILL_METRICS_API_KEY` as a Bearer
token. Anonymous or incorrectly authenticated requests receive no Prometheus payload. Configure the
monitoring integration's scrape request with the header `Authorization: Bearer <secret>` and keep
the secret in the integration's encrypted credential store, never in dashboards, source, logs, or
support messages. Verify the integration from an authorized environment:

```shell
curl --fail-with-body \
  --header "Authorization: Bearer $RUMOR_MILL_METRICS_API_KEY" \
  https://<app-name>.herokuapp.com/metrics
```

Local development does not require a metrics credential, so `curl http://127.0.0.1:8787/metrics`
remains the standard local workflow. Health endpoints stay public and expose only liveness,
coarse component readiness, and coarse product availability.

## Autonomous story startup and recovery

The release bootstrap starts a Lighthouse season at its current wall time. The first authored beat
is due after five simulation minutes; with the default five-second worker poll it should normally
appear as a completed `lighthouse_story` job and public `story_card` within six minutes of a new
season. Later beats use their earliest authored story day, while routine scenes use their authored
day and start time. Idempotency keys make every beat and routine occurrence enqueue exactly once.

If the clock advances but no output appears:

1. Check `/health/ready`. `worker=ok` with `story_pipeline=degraded` identifies a fresh clock-only
   or outdated worker; redeploy the current worker image and confirm the migration ran.
2. Open `/operator/console`. The Story pipeline card must say `Operational`; it shows the last clock
   advancement, enqueue, completion, and current queue depth.
3. Inspect the run's job counts and recovery page. Pending jobs indicate claim/execution trouble;
   failed or dead jobs include a safe error summary and the existing explicit retry action.
4. Confirm the run is `running`, its clock mode is `wall`, and its simulation time has crossed the
   five-minute first-beat boundary. A paused/manual run will not autonomously advance.
5. Recover according to the displayed state:
   - **No jobs after six minutes:** verify a running `wall` season and the stored beat graph, rerun
     the idempotent bootstrap, then restart the worker. A missing clock-advancement timestamp points
     to clock polling or run configuration rather than the provider.
   - **Queue depth is accumulating:** inspect worker logs and the oldest pending/failed job, correct
     database, worker-capacity, or provider availability, then restart the worker. Readiness becomes
     degraded when an available job makes no progress for 15 minutes.
   - **Repeated failures:** use the run recovery page's safe error category, fix the common cause,
     and explicitly retry eligible jobs. Dead jobs require code/config correction and a deploy; do
     not repeatedly retry them or expose their payloads in alerts.

Do not manually advance unless diagnosing a clock problem; normal production output requires no API
invocation. Alerts should use only the bounded `story_pipeline` readiness component and
`story_pipeline_progressing`/`story_queue_depth` metrics. Never label alerts with job/run UUIDs,
visitor data, prompts, provider responses, or generated content.

Rotate the production credential whenever monitoring access changes and at least every 90 days:

1. Generate a new random secret in a secure shell with `openssl rand -hex 32`.
2. Set it with `heroku config:set RUMOR_MILL_METRICS_API_KEY=<new-secret> -a <app-name>`; this creates
   a new release and immediately invalidates the previous credential.
3. Update the monitoring integration's encrypted Bearer credential and confirm a successful scrape.
4. Confirm an anonymous request returns 401 and no `rumor_mill_` metrics, then remove any temporary
   local copy of the secret.

If the production config value is absent, `/metrics` fails closed with 503 and no metrics payload.
The exported label set is deliberately bounded and must never include credentials, visitor or run
identifiers, private content, UUIDs, raw URLs, prompts, or other unbounded values.

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
