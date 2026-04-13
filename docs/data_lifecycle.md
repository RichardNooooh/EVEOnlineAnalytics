# Data Lifecycle

## Overview

The platform treats data publication as an explicit lifecycle, not an in-place update
to a shared database file.

## Dataset Layers

### Raw / Bronze

- closest durable representation of source records
- minimally normalized
- partitioned for replay, backfill, and source correction handling
- published by ingestion jobs

### Curated

- cleaned, standardized, and analytics-ready outputs
- produced by dbt or later publisher jobs
- consumed by BI, ML, and APIs

## Publication Lifecycle

### 1. Extract

An Airflow task or batch job fetches source records from everef.net or ESI.

### 2. Stage Candidate Output

The writer produces candidate Parquet files in a temporary, unpublished location.

### 3. Validate

The writer validates:

- schema contract
- partition contract
- duplicate or idempotency expectations
- source-specific invariants

### 4. Publish

The writer promotes the validated output into the canonical dataset path and writes a
manifest describing the publication.

### 5. Consume

Downstream readers such as dbt, ML jobs, dashboards, and APIs consume only published
dataset state.

## Backfills and Corrections

The architecture expects source corrections and replay.

- everef archives may change as new history is discovered
- backfills may replace or republish prior partitions
- publication manifests must make the visible partition set explicit

## Single-Writer Rules

- only one writer may publish a given dataset scope at a time
- readers may be concurrent
- unpublished temporary output must not be treated as visible state
- retry logic must preserve idempotent publication semantics

## Planned dbt Lifecycle

dbt will eventually:

- treat published Parquet datasets as external sources
- materialize curated outputs as Parquet datasets and/or use a transient local DuckDB
  work database during execution
- never depend on a cluster-shared writable DuckDB warehouse file
