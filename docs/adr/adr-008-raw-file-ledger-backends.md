---
status: accepted
date: 2026-05-13
tags:
  - data
  - ingestion
  - postgresql
amended: []
---

# ADR-008 - Raw Source-File Ledger Backends

## Context

Raw source-file acquisition records cache hits, downloads, checksums, source metadata,
failed acquisitions, and pruning decisions before dlt publishes analytical tables into
DuckLake. This ledger is source acquisition metadata, not the DuckLake table catalog and
not a dataset publication manifest.

Supported ingestion runtime is the Airflow Docker Compose harness in `infra/local/` and
future platform-managed Airflow deployments. Those multi-container runtimes need a
database endpoint instead of a writable SQLite file, and the project already treats
PostgreSQL as durable metadata infrastructure for production-style services.

## Decision

Use PostgreSQL for the raw source-file ledger.

- Airflow Docker Compose uses PostgreSQL through `--raw-ledger-url`.
- Future k3s/Airflow ingestion pods should pass `--raw-ledger-url` from their job
  configuration or secrets.
- The raw-file ledger remains single-writer for the relevant acquisition scope.
- The raw-file ledger is separate from the DuckLake catalog and from durable analytical
  table state.

## Consequences

### Positive

- PostgreSQL reuse keeps durable metadata technology consistent with Airflow and
  DuckLake production-style catalog choices.
- Configuration is explicit: one canonical ledger URL points at the PostgreSQL ledger.

### Negative

- Operators must provision and back up another PostgreSQL database or schema for
  ingestion runs.
- Docker Compose users with an existing Postgres volume must reset the volume or create
  the `raw_files` database and user manually, because Postgres init scripts run only on
  first initialization.
- The database backend does not by itself remove the single-writer acquisition contract.

## Alternatives Considered

- *SQLite everywhere:* Rejected because supported ingestion runs are multi-container and
  must not depend on mutable SQLite files.
- *SQLite for local development only:* Rejected because supported ingestion development
  happens through the Airflow Docker Compose runtime rather than direct host execution.
- *DuckLake catalog as raw acquisition ledger:* Rejected because source acquisition
  metadata has different lifecycle and semantics than analytical table publication.
- *SQLAlchemy and migrations now:* Deferred. Current ledger operations are small enough
  for direct DB-API implementations. A migration tool can be introduced if schema
  evolution becomes non-trivial.
