# ADR 0004: Server-rendered, progressively enhanced web UI

- Status: accepted
- Date: 2026-08-02

## Context

The product is primarily a reading experience. The MVP needs fast initial delivery, shareable URLs,
accessible content, and a small number of interactions, not a complex client-side application.

## Decision

Render HTML on the server through the FastAPI web boundary. Use semantic HTML and CSS first, then
small, replaceable JavaScript or HTML-over-the-wire enhancements where interaction materially
benefits. Presentation view models are projections of domain state and contain no domain rules.

## Consequences

The browser ships less code and core reading remains usable without JavaScript. The team avoids a
separate frontend deployment and duplicated client data model. A rich SPA, native client, or public
client API is outside the MVP and would require demonstrated interaction needs and a new ADR.
