---
status: accepted
date: 2026-05-13
tags:
  - data
  - ingestion
  - postgresql
  - sqlite
amended: []
---

# ADR 021 - Raw Source-File Ledger Backends

## Context

Raw source-file acquisition records cache hits, downloads, checksums, source metadata,
failed acquisitions, and pruning decisions before dlt publishes analytical tables into
DuckLake. This ledger is source acquisition metadata, not the DuckLake table catalog and
not a dataset publication manifest.

Direct local ingestion benefits from a zero-service SQLite ledger. Docker Compose and
future k3s/Airflow workloads need a database endpoint instead of a shared writable
SQLite file, because the project already rejects cluster-shared mutable database files on
NFS and treats PostgreSQL as durable metadata infrastructure for production-style
deployments.

## Decision

Use URL-selected raw source-file ledger backends.

- Direct local ingestion defaults to SQLite at `sqlite:///<raw-root>/raw_files.sqlite`.
- Docker Compose uses PostgreSQL through `EVE_MARKET_RAW_FILES_LEDGER_URL`.
- Future k3s/Airflow ingestion pods should receive `EVE_MARKET_RAW_FILES_LEDGER_URL`
  from Kubernetes Secrets.
- The raw-file ledger remains single-writer for the relevant acquisition scope.
- The raw-file ledger is separate from the DuckLake catalog and from durable analytical
  table state.

## Consequences

### Positive

- Local ingestion stays simple and service-free by default.
- Deployed runtimes avoid writable shared SQLite files on mounted storage.
- PostgreSQL reuse keeps durable metadata technology consistent with Airflow and
  DuckLake production-style catalog choices.
- Configuration is explicit: one canonical ledger URL selects the backend.

### Negative

- Operators must provision and back up another PostgreSQL database or schema for
  deployed ingestion runs.
- Docker Compose users with an existing Postgres volume must reset the volume or create
  the `raw_files` database and user manually, because Postgres init scripts run only on
  first initialization.
- The database backend does not by itself remove the single-writer acquisition contract.

## Alternatives Considered

- *SQLite everywhere:* Rejected because mounted/shared deployments must not depend on a
  cluster-shared writable SQLite file.
- *PostgreSQL everywhere:* Rejected because direct local ingestion should remain runnable
  without starting service dependencies.
- *DuckLake catalog as raw acquisition ledger:* Rejected because source acquisition
  metadata has different lifecycle and semantics than analytical table publication.
- *SQLAlchemy and migrations now:* Deferred. Current ledger operations are small enough
  for direct DB-API implementations. A migration tool can be introduced if schema
  evolution becomes non-trivial.
