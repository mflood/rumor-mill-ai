# ADR 0001: FastAPI at the web boundary

- Status: accepted
- Date: 2026-08-02

## Context

The MVP needs health and operational endpoints, HTML routes, and a small set of application APIs.
The team is building the engine in Python and benefits from typed request/response validation.

## Decision

Use FastAPI as the HTTP composition layer. Route handlers validate transport input, invoke
application use cases, and map results to HTTP or presentation models. Domain and engine modules do
not import FastAPI types. Construct the app through a factory so dependencies can be replaced in
tests.

## Consequences

The web and worker processes can share application code without coupling the engine to HTTP.
FastAPI's dependency injection and OpenAPI support are available where useful. This is not a
commitment to expose every application use case as a public JSON API.
