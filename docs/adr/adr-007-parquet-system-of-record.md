---
status: accepted
date: 2026-04-13
tags:
  - data
  - storage
  - compute
amended:
  - 2026-05-10
---

# ADR-007 - Parquet Datasets as the System of Record

> Current status: refined by ADR-008. Parquet remains the physical data file format,
> but DuckLake tables are now the canonical analytical table contract.

## Context

The earlier architecture modeled DuckDB as a shared writable warehouse file on NFS.
That design kept costs low, but it made persistence, publication, and concurrency
semantics too implicit. The project needs a clearer contract for what is durable,
what is mutable, and what a writer is allowed to change.

## Decision

This ADR originally established a Parquet dataset contract on shared storage. ADR-008
refines that contract: **DuckLake tables backed by Parquet data files are now the
system of record**.

The current contract is:

- Shared NFS storage holds DuckLake data files, dataset manifests/contracts, Airflow
  logs, and MLflow artifacts.
- DuckLake catalog metadata is durable state and must be managed with the data files;
  mounted/shared deployments require non-local durable catalog storage such as
  PostgreSQL.
- Published DuckLake table state is the persisted analytical source of truth.
- Each dataset publication has a **single writer** for the affected publication scope.
- PostgreSQL advisory locks keyed by publication scope enforce that single-writer
  rule; scheduler-level limits such as Airflow `max_active_runs=1` are outer guards
  rather than the source of truth.
- Writers publish through DuckLake table commits or merge/delete-insert semantics (refined
  by ADR-008 amendment: insert-new-by-key is the current practice) rather
  than mutating shared DuckDB database state in place.
- DuckDB is allowed only as **local or transient compute** for development and
  single-writer batch jobs.
- There is **no cluster-shared writable `.duckdb` file**.
- Mounted/shared DuckLake storage with a SQLite catalog is rejected.
- Any DuckDB database used by dbt or a batch job must live on pod-local scratch such
  as `emptyDir` or node-local `ReadWriteOnce` storage.

## Publication Semantics

A planned table publication must follow this contract:

1. Write candidate data into unpublished job state.
2. Validate the candidate output against the dataset contract.
3. Commit the DuckLake table change for the relevant replacement scope.
4. Emit or update supporting manifest metadata where useful.
5. Only after commit may downstream readers treat the data as visible.

The exact implementation can vary later, but future code must preserve the semantic
boundary between unpublished scratch output and published table state.

## Storage and Compute Split

### Storage

- Durable, shared, reader-visible state.
- Represented as DuckLake data files, catalog metadata, manifests, and contracts.
- Safe for many readers.
- Writes are governed by single-writer publication rules.

### Compute

- Local execution state used to read, join, validate, aggregate, or publish data.
- DuckDB may be used here because it is effective embedded analytical compute.
- Compute state is disposable and must not be treated as the durable system of record.

## Consequences

### Positive

- Durable state is file-format-oriented and easy to reason about.
- Shared readers consume stable published table state instead of an actively mutated
  database file.
- Single-writer boundaries are explicit.
- Local DuckDB remains available where it is strongest: local analysis, dbt execution,
  and batch transforms with isolated scratch state.

### Negative

- Publication semantics have to be designed explicitly.
- Dataset layouts, partitioning, and manifests become first-class contracts that must
  be documented.
- Some workflows that are trivial in a mutable warehouse need clearer writer rules.

## Alternatives Considered

- *Keep the shared DuckDB file on NFS:* Rejected because it keeps storage and compute
  entangled and leaves publication semantics too implicit.
- *Move immediately to a managed warehouse:* Rejected for steady state because it does
  not fit the budget target, though Snowflake remains as a cloud-readiness proof.
- *Use object storage first and NFS later:* Rejected for now because the homelab already
  has shared NFS, and this ADR is about the persistence contract rather than the
  backing protocol.

## Amendments

- 2026-05-10 - Refined by ADR-008
  - ADR-008 adopts DuckLake as the canonical lakehouse table format. Parquet remains
    the physical data file format, but plain filesystem Parquet alone is no longer the
    long-term canonical table storage contract.
