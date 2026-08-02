# CI/CD and production recovery

The `CI` GitHub Actions workflow validates pull requests and commits to `main`. Its required gates
cover formatting, linting, typing, the full test suite, the complete migration upgrade/rollback
chain, authored-world validation, and deterministic critical narrative evaluations. Superseded
branch runs are cancelled, and uv's dependency cache is reused between runs.

Configure branch protection for `main` to require the five validation jobs and disallow direct
pushes. Configure the GitHub `production` environment with any desired reviewer approval and:

- secret `HEROKU_API_KEY`: a deploy-capable Heroku API key;
- variable `HEROKU_APP_NAME`: the production Heroku application name;
- variable `PRODUCTION_URL`: its HTTPS origin, without a trailing path.

Only a green `main` run reaches the `deploy` job. Production deployments never cancel one another.
Heroku's release process applies migrations before promoting the new web and worker processes, and
the workflow then verifies infrastructure readiness independently from product readiness. Its
playable smoke creates a visitor session, reaches Today through the real entry redirect, and opens
at least one location or character destination.

## Failed migration

1. Treat the release as not deployed; do not bypass Heroku's failed release phase.
2. Inspect `heroku logs --tail --ps release -a <app-name>` and identify the failed revision.
3. Before any data-changing recovery, capture a backup with
   `heroku pg:backups:capture -a <app-name>` and verify it appears in
   `heroku pg:backups -a <app-name>`.
4. Prefer a forward-compatible corrective migration. Validate its complete upgrade, downgrade, and
   re-upgrade chain locally, then merge it through the normal protected-branch workflow.
5. Use `alembic downgrade` against production only after explicit review of the migration's data
   loss risk and a tested restore plan.

## Failed production smoke test

1. The deployment has completed but is not verified. Stop further releases. Check
   `/health/ready` for infrastructure and `/health/product` for playability, then inspect
   `heroku ps -a <app-name>` plus web, worker, and release logs.
2. Classify the failure before changing production:
   - `missing_world` or `invalid_world`: the Lighthouse seed is absent or invalid; inspect the
     release log and rerun the idempotent bootstrap after correcting the packaged definition.
   - `no_running_season`: every Lighthouse run is paused or ended; inspect run status and resume
     the intended season through the operator console, or rerun bootstrap if none exists.
   - `/health/ready` reports `worker=degraded`: restore the worker dyno and verify a fresh heartbeat;
     do not alter story data.
   - `/health/ready` reports `provider=degraded`: correct provider configuration or availability;
     do not create or resume runs to mask it.
3. If configuration or process health can be corrected safely, fix it and rerun
   `uv run python scripts/smoke_deployment.py <production-url>`.
4. Otherwise find the last verified release with `heroku releases -a <app-name>` and run
   `heroku rollback <release> -a <app-name>`.
5. Watch the rollback release phase and rerun the smoke command. A rollback is complete only after
   the smoke check passes.

## General rollback

Heroku rollback creates a new release from earlier code but does not reverse database changes.
Confirm the older code is compatible with the current schema before rolling back. If it is not,
restore a verified database backup or ship a reviewed forward fix; never improvise a destructive
schema downgrade during an incident. Record the failed and recovered release IDs in the incident
notes, then open a follow-up issue for the underlying cause.
