---
status: superseded
date: 2026-03-28
tags:
  - tools
amended:
  - 2026-04-13
superseded_by: ADR-016
---

# ADR 005 - Superseded: DuckDB as Primary Warehouse

## Context

The project originally needed a zero-cost analytical store for dbt transformations,
ML feature engineering, and local development. DuckDB was chosen early because it is
embedded, fast, and simple to operate.

## Original Decision

ADR-005 originally established DuckDB as the primary warehouse, with a shared writable
`.duckdb` file placed on NFS-backed persistent storage.

## Current Status

This ADR is superseded by ADR-016.

The repository no longer treats a cluster-shared writable DuckDB file as the system of
record. The current contract is:

- Published Parquet datasets on shared storage are the system of record.
- DuckDB is local or transient compute for development and single-writer batch jobs.
- There is no cluster-shared writable `.duckdb` file.

## Historical Rationale

The original decision was reasonable at the time because DuckDB offered:

- zero license cost
- no server process to manage
- strong analytical performance for the planned market-data scale

What changed was not DuckDB's usefulness as a compute engine. What changed was the
storage contract. Shared mutable database files on RWX storage make publication,
concurrency, and recovery semantics less explicit than a dataset-oriented design with
single-writer publication rules.

## Amendments

- 2026-04-13 - Superseded by ADR-016
  - ADR-016 replaces the shared DuckDB warehouse contract with a single-writer Parquet
    dataset architecture. DuckDB remains in the stack only as local or transient
    compute, not as cluster-shared writable storage.
