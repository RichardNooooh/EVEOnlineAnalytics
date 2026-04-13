---
status: accepted
date: 2026-04-13
tags:
  - data
  - storage
  - compute
amended: []
---

# ADR 016 - Parquet Datasets as the System of Record

## Context

The earlier architecture modeled DuckDB as a shared writable warehouse file on NFS.
That design kept costs low, but it made persistence, publication, and concurrency
semantics too implicit. The project needs a clearer contract for what is durable,
what is mutable, and what a writer is allowed to change.

## Decision

The architecture now uses **published Parquet datasets on shared storage as the system
of record**.

The contract is:

- Shared NFS storage holds Parquet datasets, dataset manifests, contracts, Airflow
  logs, and MLflow artifacts.
- Published Parquet datasets are the persisted analytical source of truth.
- Each dataset publication has a **single writer** for the affected publication scope.
- Writers publish via **temp-write then promote** semantics rather than mutating shared
  database state in place.
- DuckDB is allowed only as **local or transient compute** for development and
  single-writer batch jobs.
- There is **no cluster-shared writable `.duckdb` file**.
- Any DuckDB database used by dbt or a batch job must live on pod-local scratch such
  as `emptyDir` or node-local `ReadWriteOnce` storage.

## Publication Semantics

A planned dataset publication must follow this contract:

1. Write candidate Parquet files into a temporary staging path that is not a published
   reader path.
2. Validate the candidate output against the dataset contract.
3. Emit or update a publication manifest that identifies the promoted files or
   partition set.
4. Promote the publication to the canonical dataset location.
5. Only after promotion may downstream readers treat the data as visible.

The exact implementation can vary later, but future code must preserve the semantic
boundary between unpublished scratch output and published dataset state.

## Storage and Compute Split

### Storage

- Durable, shared, reader-visible state.
- Represented as Parquet datasets, manifests, and contracts on shared NFS.
- Safe for many readers.
- Writes are governed by single-writer publication rules.

### Compute

- Local execution state used to read, join, validate, aggregate, or publish data.
- DuckDB may be used here because it is effective embedded analytical compute.
- Compute state is disposable and must not be treated as the durable system of record.

## Consequences

### Positive

- Durable state is file-format-oriented and easy to reason about.
- Shared readers consume stable published datasets instead of an actively mutated
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
