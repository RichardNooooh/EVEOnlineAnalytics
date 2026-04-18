---
status: deferred
date: 2026-04-18
tags:
  - infra
  - airflow
  - postgresql
amended: []
---

# ADR 019 - PgBouncer for Airflow Metadata PostgreSQL

## Context

ADR-018 establishes external PostgreSQL as the baseline architecture for the Airflow
metadata database.

Airflow is a distributed system with multiple components that can create significant
database connection fan-out. The [Apache Airflow Helm chart production
guide](https://airflow.apache.org/docs/helm-chart/stable/production-guide.html)
explicitly notes that Airflow can open many database connections and recommends
enabling PgBouncer when PostgreSQL is used.

PgBouncer would reduce the number of direct PostgreSQL backend connections and could
protect the metadata database from connection pressure. This matters because PostgreSQL
sizes some resources directly from `max_connections`, including shared memory. See the
[PostgreSQL connection settings
documentation](https://www.postgresql.org/docs/current/runtime-config-connection.html).

However, PgBouncer is not a free optimization. It introduces another component to
operate, monitor, and debug. Pooling mode also matters: the [PgBouncer feature
documentation](https://www.pgbouncer.org/features.html) makes clear that transaction
pooling has compatibility trade-offs for session-oriented PostgreSQL behavior.

## Decision

Defer the PgBouncer layer for the Airflow metadata database.

The accepted baseline remains external PostgreSQL on its own. PgBouncer is documented
as a future architectural enhancement that may be adopted once the external metadata
database deployment is in place and its connection behavior is understood well enough
to choose and validate an appropriate pooling mode.

## Rationale

- The project should first establish the external PostgreSQL metadata database as the
  baseline architecture before adding another critical component in front of it.
- Deferring PgBouncer keeps the accepted architecture narrower while still documenting
  the likely next step for database protection and connection management.
- Pooling mode should be chosen deliberately rather than assumed. Transaction pooling in
  particular has compatibility trade-offs for session-oriented PostgreSQL behavior, so
  the final mode should be validated against the eventual Airflow deployment.
- PgBouncer remains a strong candidate for a later production hardening step if Airflow
  metadata traffic creates enough connection pressure to justify the extra operational
  complexity.
