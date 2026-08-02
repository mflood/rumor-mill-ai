# ADR 0002: Postgres as the system of record

- Status: accepted
- Date: 2026-08-02

## Context

Scenes, canon, memories, beliefs, rumors, schedules, and job outcomes are relational, durable data.
Story updates need transactions, constraints, provenance queries, and deterministic ordering.

## Decision

Use Postgres for authoritative domain state, presentation projections, and MVP job coordination.
Access it through repository and unit-of-work ports defined inward of the adapter. Apply schema
changes with versioned migrations. Store provider payloads only when useful for reproducibility and
after removing secrets or sensitive metadata.

## Consequences

A single transaction can keep story state consistent, and operators can inspect failures with
ordinary queries. The MVP does not add a document database, vector database, cache, or message
broker until a measured requirement cannot be met responsibly with Postgres.
