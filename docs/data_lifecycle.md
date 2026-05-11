# Data Lifecycle

## Overview

The platform treats data publication as an explicit lifecycle, not an in-place update
to a shared DuckDB database file. DuckLake table state is the canonical analytical
contract; Parquet files are the physical storage below that table format.

## Dataset Layers

### Raw / Bronze

- closest durable representation of source records
- minimally normalized
- organized for replay, backfill, and source correction handling
- published by ingestion jobs

### Curated

- cleaned, standardized, and analytics-ready outputs
- produced by dbt or later publisher jobs
- consumed by BI, ML, and APIs

## Publication Lifecycle

### 1. Extract

An Airflow task or batch job fetches source records from everef.net or ESI.

### 2. Stage Candidate Output

The writer produces candidate data in job-local or unpublished state before it becomes
visible table state.

### 3. Validate

The writer validates:

- schema contract
- partition contract
- duplicate or idempotency expectations
- source-specific invariants

### 4. Publish

The writer commits the validated change into the canonical DuckLake table state. For
sources that can revise prior files, the replacement scope must be explicit, such as the
Everef market-history source `date`.

For ingestion jobs, DuckLake destination configuration is part of the publisher
boundary: the publisher resolves the catalog, storage path, and publication guardrails
before committing data.

### 5. Consume

Downstream readers such as dbt, ML jobs, dashboards, and APIs consume only published
table state.

## Backfills and Corrections

The architecture expects source corrections and replay.

- everef archives may change as new history is discovered
- backfills may replace or republish prior partitions
- DuckLake table state must make the visible replacement scope explicit
- supplemental manifests may record publication metadata where useful

## Single-Writer Rules

- only one writer may publish a given dataset scope at a time
- readers may be concurrent
- unpublished temporary output must not be treated as visible state
- retry logic must preserve idempotent publication semantics
- mounted/shared DuckLake storage must use a non-local durable catalog such as
  PostgreSQL; local SQLite catalogs are limited to local smoke tests

## Planned dbt Lifecycle

dbt will eventually:

- read canonical DuckLake table state through a validated DuckLake/DuckDB handoff
- materialize curated outputs as DuckLake tables and/or use a transient local DuckDB
  work database during execution
- never depend on a cluster-shared writable DuckDB warehouse file

## Local Development Lifecycle

Local Compose Airflow + dlt supports the same publication-oriented development loop on
a single workstation. It is for fast iteration and demos, not production deployment.

Expected loop:

1. edit ingestion and dlt code
2. run locally against `.local/data`
3. validate DAG behavior and outputs through local Airflow
4. commit code and contracts
5. let CI build and test the deployable image/artifacts
6. deploy to k3s with Helm

Local storage remains an approximation of production storage. `.local/data` stands in
for TrueNAS NFS DuckLake data-file storage, local Postgres stands in for the Airflow
metadata database, and bind-mounted DAGs/code stand in for the deployed Airflow image or
sync mechanism.
