# ADR 0003: Durable background execution through Postgres

- Status: accepted
- Date: 2026-08-02

## Context

Scheduled beats and AI generation can outlive an HTTP request, fail transiently, and be retried.
Adding a broker and a distributed task platform would increase MVP operations and failure modes.

## Decision

Run background work in a separate worker process using persisted Postgres job records. Workers
atomically claim due jobs with leases or row locking, perform provider calls outside story-state
transactions, and commit validated results through idempotent application commands. Persist attempt
counts, next-attempt time, terminal failure details, and correlation identifiers.

## Consequences

Work survives process restarts and remains observable without a new infrastructure dependency.
Web requests enqueue or schedule work but do not wait for generation. This design accepts modest
polling latency. A dedicated queue requires a later ADR supported by throughput or latency evidence.
