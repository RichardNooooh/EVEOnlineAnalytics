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
- current implemented curated BI marts are `curated_daily_prices` and
  `curated_trade_volume`

## Publication Lifecycle

### 1. Extract

An Airflow task or batch job fetches source records from everef.net or ESI.

### 2. Stage Candidate Output

The writer produces candidate data in job-local or unpublished state before it becomes
visible table state.

For ingestion, this includes `dlt` runtime state. The packaged host CLI keeps that
state repo-local under `ingestion/.dlt/.var/<profile>/` and `ingestion/.local/`, while
Docker, Airflow, and Kubernetes-style runs should place it on explicit ephemeral
scratch separate from DuckLake durable storage and shared mounts.

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

For curated dbt outputs, upstream build steps happen in scratch DuckDB first and the
final BI mart models then materialize directly into curated DuckLake tables such as
`curated.curated_daily_prices` or `curated.curated_trade_volume`.

### 5. Consume

Downstream readers such as dbt, ML jobs, dashboards, and APIs consume only published
table state.

For the local BI path, Compose-run Evidence reads the published curated DuckLake table
state from the local reviewer/demo data root. It does not read dbt scratch databases or
unpublished intermediate tables.

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
- durable state remains DuckLake data plus PostgreSQL-backed services, not container
  runtime scratch

## Curated dbt Lifecycle

Current contract for curated BI publication:

1. dbt reads canonical raw DuckLake table state through an attached DuckLake alias.
2. dbt builds staging, intermediate, and fact models in a transient local DuckDB work database.
3. final curated mart models materialize directly into attached curated DuckLake tables.
4. dbt data tests validate those published relations after materialization.
5. Evidence and other readers consume that published curated state.

This direct dbt publication path does not provide a pre-visibility validation barrier for
curated tables.

dbt must never depend on a cluster-shared writable DuckDB warehouse file.

## Local Development Lifecycle

Local Compose Airflow + dlt supports the same publication-oriented development loop on
a single workstation. It is for fast iteration and demos, not production deployment;
production-style runtime is managed by the platform repo.

Expected loop:

1. edit ingestion and dlt code
2. build the local ingestion job image
3. run locally against `.local/data`
4. validate DAG behavior and outputs through local Airflow DockerOperator tasks
5. run host dbt against local Compose PostgreSQL-backed DuckLake catalogs
6. validate local BI through Compose Evidence service
7. commit code and contracts
8. let CI validate changes and publish GHCR image tags from trusted `master` builds
9. deploy through `homelab-data-platform` into the production Airflow runtime

Local storage remains an approximation of production storage. `.local/data` stands in
for TrueNAS NFS DuckLake data-file storage, local Postgres stands in for the Airflow
metadata database and raw-file acquisition ledger, and bind-mounted DAGs/code stand in
for the deployed Airflow image or sync mechanism.

Within that split, the packaged host CLI uses repo-local `dlt` state under
`ingestion/.dlt/.var/<profile>/` and `ingestion/.local/`, while containerized local
Airflow and later k3s runs should use explicit ephemeral scratch for `dlt` runtime
state.

Local Airflow may use DockerOperator with `eve-market-ingestion:local` to match the
container boundary used later by KubernetesPodOperator. The deployable ingestion image is
published by the `Ingestion Image` GitHub Actions workflow as
`ghcr.io/<owner>/eve-market-ingestion:<immutable-tag>`. Local Docker socket access is a
local-only development shortcut and is not part of the k3s deployment contract.

Future hardening may move containerized runtimes to read-only root filesystems with
explicit scratch mounts.
