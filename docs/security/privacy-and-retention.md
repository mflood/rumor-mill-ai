# Security, privacy, and data retention

Rumor Mill's MVP uses a random, pseudonymous visitor cookie. It does not require an account,
collect an email address, or intentionally collect real-world identity. Visitor text can still
contain personal information, so it is treated as private data.

## Data inventory and retention

| Data | Contents and purpose | Retention / deletion |
| --- | --- | --- |
| Visitor session | Hashed random token, timestamps, pseudonymous UUID | Expires after `RUMOR_MILL_VISITOR_SESSION_DAYS` (365 days by default); permanently deleted on visitor reset. Raw cookie tokens are never stored. |
| Conversations | Visitor text, generated replies, character/run references | Retained with the visitor session for return visits; cascade-deleted on visitor reset. |
| Character relationship state | Per-character trust, summary, scoped memories | Retained with the visitor session; cascade-deleted on visitor reset. |
| Narrative reports | Category, optional visitor note, opaque diagnostic references | Retained with the visitor session; cascade-deleted on visitor reset. |
| Generated/public content | World scenes, recaps, episodes, artifacts | Part of the shared simulation, not visitor-owned; retained for the life of the run and removed when that run is deleted. |
| Simulation state and jobs | Authored world, events, beliefs, jobs, results | Operational product data; retained for the life of the run. Failed-job errors must not contain prompts, secrets, or dialogue. |
| Operator audit | Privileged action, opaque resource ID, safe metadata | Append-only launch audit record; retain for at least one year, then delete under the operational archive process. |
| Application logs and metrics | Request method/path/status, correlation IDs, counts, latency, provider usage/error codes | Do not contain cookies, authorization headers, prompts, visitor text, or model output. Production platform logs should be configured for 30 days; metrics for 90 days. |

Expired sessions are inaccessible immediately. Operations must periodically purge expired visitor
rows so the database does not retain inaccessible data past the configured session period.

## Model-provider transmission

The configured model provider receives the minimum conversation context needed for one character,
run, and visitor turn: fixed policy, scoped world/character state, recent dialogue, and the current
visitor message. It does not receive the visitor cookie, token hash, operator key, database URL,
unrelated visitor records, or application secrets. Provider retention and training controls are
governed by the provider account's data-control settings and must be reviewed before production.

## Visitor deletion

`DELETE /api/v1/visitors/session` and the **Erase my visit data** server-rendered action permanently delete
the visitor row, conversations, relationship state, and reports in one transaction, then expire the
browser cookie. Shared canonical simulation and published content are intentionally unaffected.
Starting a new session rotates the identity and deletes an existing cookie-linked identity.

## Web-control review

- Cookies are `HttpOnly`, `SameSite=Lax`, scoped to `/`, and `Secure` by default.
- Cookie-authenticated writes with an `Origin` header must be same-origin; SameSite is the fallback
  for browsers that omit it. Cross-origin response sharing is not enabled (no CORS allowlist).
- New-session creation rotates any presented visitor identity, preventing session fixation.
- Per-client rate limiting covers non-health endpoints. Operator writes separately require a bearer
  secret and explicit confirmation for destructive actions.
- Production metrics require a separate Bearer secret. Metric labels are bounded operational
  categories and must not contain raw paths, credentials, visitor/run identifiers, UUIDs, prompts,
  private content, or other high-cardinality values.
- Responses set CSP, clickjacking protection through `frame-ancestors`, MIME-sniffing protection, a
  same-origin referrer policy, and a restrictive permissions policy.
- Inputs use strict Pydantic schemas and bounded lengths; SQLAlchemy parameterization prevents SQL
  injection. Prompt and output controls are documented separately.

TLS termination and production log/provider retention are deployment responsibilities and must be
verified in the launch environment.
