---
status: deferred
date: 2026-03-28
tags:
  - data
amended: []
---

# ADR 007 - Streaming Component as Future Enhancement

## Context

The EVE ESI API provides order snapshots approximately every 5 minutes (twice
per hour for some endpoints). A streaming layer could poll these snapshots and
publish them as events for near-real-time processing.

## Decision

Defer the streaming component (Kafka or Redis Streams) to a post-MVP phase. It
is identified as the addition that pushes the project from an 8.5 to a 9 out of 10
in quality.

## Rationale

- The MVP pipeline uses batch processing via Airflow DAGs: daily ESI market history
  pulls and hourly (or more frequent) order snapshot loads.
- Adding a streaming layer requires additional infrastructure (broker deployment,
  consumer groups, schema management) that competes for the ~39 GB RAM budget.
- The batch pipeline must be stable and proven before adding streaming complexity.
- The feature is explicitly scoped for post-MVP work and documented as a planned enhancement.
