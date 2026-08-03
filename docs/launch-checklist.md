# Public MVP launch checklist

Owner: project maintainer
Last reviewed: 2026-08-03

This checklist is the release record for The Lighthouse public MVP. Check an item only against the
candidate production release. Record the release ID, reviewer, date, and evidence link in the PR or
release notes.

## Release identity and content

- [ ] The production commit matches the reviewed release and the repository link resolves to
  `https://github.com/mflood/rumor-mill-ai`.
- [ ] `docs/worlds/lighthouse/world.json` passes validation and the included Lighthouse story
  documents have received human editorial review.
- [ ] A fresh staging database is seeded with `make seed-lighthouse`.
- [ ] One complete 14-day accelerated season has been generated with the deterministic fake
  provider; attach `artifacts/lighthouse-smoke-transcript.md` and the narrative evaluation report.
- [ ] Live demo, canonical URLs, page titles, descriptions, social-card image, favicon, repository
  links, and `/lighthouse/feedback` all resolve over HTTPS.

## Experience pass

- [ ] Current Chrome, Firefox, and Safari: first visit, enter story, Today, Town, People, Archive,
  feedback, session reset, and browser Back all work. Every entered active-visit page shows
  **Today · Town · People · Archive** in that order; before entry, Archive is public and People is
  hidden.
- [ ] iOS Safari and Android Chrome at 320, 375, and 768 CSS pixels have no horizontal overflow;
  controls remain usable with one hand and at 200% zoom.
- [ ] Keyboard-only navigation has a visible focus indicator, logical order, working skip links,
  and no traps. The four-item global navigation has an accessible name, follows DOM/focus order,
  and marks exactly one destination with `aria-current="page"`. VoiceOver or NVDA announces
  landmarks, headings, status messages, and controls.
- [ ] Reduced motion, forced colors, images disabled, JavaScript disabled, slow network, and offline
  failure states remain understandable and recoverable.
- [ ] Empty Archive/Town/People states, zero-publication and quiet active visits, paused/completed
  seasons, both between-season history states, expired sessions, unavailable characters/provider,
  duplicate submit, validation errors, and report failures provide a next action without exposing
  internal run IDs, hidden story state, or another visitor's notes.
- [ ] No broken internal links. The production smoke check passes:
  `uv run python scripts/smoke_deployment.py <production-url>`.
- [ ] Lighthouse mobile scores are recorded for the landing and Today pages: performance >= 90,
  accessibility >= 95, best practices >= 95, and SEO >= 95, or an exception is documented.

## Operations and safeguards

- [ ] **Rollback owner:** the person deploying is named in the release record and can execute the
  tested procedure in `docs/ci-cd.md`.
- [ ] **Budget limits:** Heroku dyno/Postgres limits and OpenAI project monthly budget/rate limits
  are configured; the expected ceiling and alert recipients are recorded outside the repository.
- [ ] **Monitoring:** `/health/live`, `/health/ready`, `/health/product`,
  `rumor_mill_playable_story_available`, worker freshness, HTTP 5xx rate, job lag,
  provider errors, latency, and spend alerts are active and reach the on-call owner. The production
  metrics scrape uses the dedicated Bearer credential documented in `docs/heroku-deployment.md`.
- [ ] A current database backup exists and the deployed code is compatible with the current schema.
- [ ] Known limitations are copied from the README into release notes: anonymous browser-local
  identity, no cross-device sync, authored question paths, one demo world, and evolving API/authoring
  format.
- [ ] A metrics review is scheduled for 24 hours and 7 days after launch covering successful entry,
  Today-to-Town progression, conversation completion, return visits, feedback volume, errors,
  latency, job lag, provider use, and spend.

## Go / no-go

- [ ] Required CI checks and deterministic narrative evaluations pass on the release commit.
- [ ] Every exception above has an owner and follow-up issue.
- [ ] The rollback owner explicitly records **GO** with the production release ID and timestamp.
