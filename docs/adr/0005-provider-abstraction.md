# ADR 0005: AI providers behind an application port

- Status: accepted
- Date: 2026-08-02

## Context

Generation capabilities, model names, structured-output formats, prices, and failure behavior vary
by provider. Domain tests must be deterministic and must not require network access.

## Decision

Define provider-neutral generation requests and validated results at the application boundary.
Operational adapters translate them to provider SDK calls. Select adapters and models through
configuration. Keep retries, timeouts, rate-limit handling, usage capture, and provider error mapping
inside adapters; keep narrative validation and acceptance rules inside the engine.

## Consequences

Tests can use deterministic fakes, and a provider can be replaced without changing story rules.
The abstraction covers capabilities the product actually uses rather than promising lowest-common-
denominator portability. Provider-specific optimizations are allowed inside adapters but may not
leak vendor types into engine, authored-world, or web contracts.
