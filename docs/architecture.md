# Architecture

## Document Scope

This document defines the analytics workload architecture for
`eve-market-analytics`. It captures durable data, publication, storage, and
compute boundaries that workload code must honor. Reusable cluster, storage,
ingress, observability, and runtime implementation belongs to the companion
platform repository `homelab-data-platform`.

## Canonical Contract

The analytics workload uses **DuckLake tables as the canonical analytical table
contract**.

- **System of record:** DuckLake table state backed by Parquet data files.
- **Physical storage:** Parquet files stored on shared storage under the DuckLake table
  format.
- **Catalog state:** DuckLake catalog metadata is durable state and must be backed up
  with the data files. Production-style or mounted/shared deployments use PostgreSQL;
  local SQLite catalogs are for local smoke tests only.
- **Shared durable state:** DuckLake data files, catalog metadata, schema contracts,
  MLflow artifacts, and Airflow logs.
- **Compute state:** local or transient execution state such as DuckDB work databases
  and `dlt` runtime scratch.
- **Service boundary:** Kubernetes runs the application workloads, while PostgreSQL runs
  as an external infrastructure dependency managed by the platform repo.
- **Forbidden pattern:** no cluster-shared writable `.duckdb` file.
- **Guardrail:** mounted/shared DuckLake storage with a SQLite catalog is rejected.

These rules are workload-facing invariants. Any local harness or production
runtime is acceptable only if it preserves this contract.

## Storage vs Compute

### Storage

Storage is durable, shared, and reader-visible.

- stored on TrueNAS NFS
- organized as DuckLake tables by layer and dataset name
- governed by DuckLake catalog state, table contracts, and supplemental manifests where
  they are useful
- safe for many readers after publication

### Compute

Compute is local and disposable.

- DuckDB may be used for local development or single-writer batch jobs
- dbt may use a local DuckDB work database during execution
- compute outputs are not canonical until published to the DuckLake table contract

## Planned Data Flow

```text
Airflow
  -> dataset writer / publisher
  -> raw or bronze DuckLake tables backed by Parquet files
  -> dbt reads canonical table state through an attached DuckLake alias in scratch DuckDB
  -> dbt build produces validated curated candidate output in scratch DuckDB
  -> curated DuckLake publish commits the replacement scope
  -> Compose-run Evidence, ML training, and APIs consume published curated table state
```

Current curated BI publication target:

- `curated.curated_daily_prices` published from `transformation/models/marts/mart_curated_daily_prices.sql`
- `curated.curated_trade_volume` published from `transformation/models/marts/mart_curated_trade_volume.sql`
- contracts documented in `../datasets/contracts/curated_daily_prices.md` and
  `../datasets/contracts/curated_trade_volume.md`

Ingestion source and pipeline code extracts and validates records; DuckLake destination
configuration and publication-specific storage/catalog policy live at the ingestion
publisher boundary.

For Everef ingestion, URL construction, source-date iteration, and HTTP probe metadata
belong to the canonical client module `ingest.clients.everef`. Market-history schema,
primary keys, and validation belong to `ingest.contracts.market_history`. The dlt source
should wire those boundaries together and stream chunks rather than own client behavior
or contract definitions.

## Local Development/Demo Runtime

The repository includes a local Docker Compose Airflow + dlt runtime as a
workload-focused development harness for fast iteration and portfolio demos.

This runtime is for development only. Reusable production-style deployment and
runtime implementation should live in `homelab-data-platform`, while this
repository remains responsible for workload contracts such as DuckLake-backed
datasets, publication semantics, orchestration expectations, and storage and
scratch requirements.

Local-to-production mapping:

- `.local/data` approximates TrueNAS NFS storage for DuckLake data files
- local Postgres approximates the Airflow metadata database and raw-file acquisition
  ledger database
- stock `apache/airflow` containers plus bind-mounted DAGs and source code approximate
  the deployed Airflow image or DAG/code sync mechanism
- local DockerOperator task containers approximate KubernetesPodOperator pods that run
  GHCR-published ingestion images in k3s
- local Evidence container approximates read-only BI runtime over curated DuckLake state

Local smoke runs may use the default SQLite DuckLake catalog. Any run using mounted
DuckLake storage, including `--storage-target mounted` or an explicit mounted
`--ducklake-storage`, must use a non-local catalog such as PostgreSQL through
`--ducklake-catalog`.

The packaged host ingestion CLI keeps `dlt` runtime state repo-local under
`ingestion/.dlt/.var/<profile>/` and `ingestion/.local/`. Docker, Airflow, and
Kubernetes-style runs should instead mount explicit ephemeral scratch for `dlt`
runtime state so that container working state stays separate from DuckLake durable
storage and shared mounts.

Raw source-file acquisition uses a separate ledger from the DuckLake publication
catalog. Direct local ingestion defaults to a local SQLite raw ledger. Docker Compose and
production-style k3s/Airflow deployments use PostgreSQL through `--raw-ledger-url`,
while preserving single-writer acquisition semantics for the relevant publication scope.

Future hardening may move containerized runtimes to read-only root filesystems with
explicit scratch mounts, but the storage contract remains the same: durable state lives
in DuckLake data files and PostgreSQL-backed services, not container-local runtime state.

Local commands:

```bash
make local-airflow-up
make local-airflow-down
make local-airflow-reset
make local-pipeline-smoke
```

See `infra/local/README.md` for current local harness details. Production-style
runtime implementation and platform operations belong in
`homelab-data-platform`.

## Single-Writer Rule

For any publication scope, exactly one writer is responsible for producing the next
published state.

Examples of publication scope:

- a full dataset
- a partition set for a dataset
- a date window being backfilled

Readers may be concurrent. Writers must not concurrently mutate the same published
scope.

## Publication Semantics

Ingestion and transform jobs publish by changing DuckLake table state, not by exposing
loose Parquet files as the contract. A publication must preserve these semantics:

1. stage candidate data in unpublished job state
2. validate data and schema contract compliance
3. commit the DuckLake table change for the intended replacement scope
4. record supporting contract or manifest metadata where needed
5. only then allow downstream readers to treat the table state as visible

For Everef market history, revised source dates are represented through DuckLake merge
or delete-insert semantics rather than append-only duplicate rows.

For the current BI path, dbt builds `fact_market_history` plus curated marts on local
scratch compute and a curated publisher commits validated `date` replacement scope into
DuckLake before Evidence readers see the result. Supported local exception: dbt runs on
host against local Compose PostgreSQL-backed DuckLake catalogs.

## Scratch Storage Contract

Any DuckDB database used by dbt or batch jobs must live on local scratch storage.

Allowed examples:

- `emptyDir`
- node-local `ReadWriteOnce` PVC
- local developer filesystem
- explicit container scratch for `dlt` runtime state

Disallowed example:

- RWX shared NFS volume containing a writable `.duckdb` file used by multiple pods

## Platform Boundary

`eve-market-analytics` owns workload semantics: dataset contracts, ingestion and
transform behavior, publication rules, and the storage and compute constraints
required for correct analytics execution. `homelab-data-platform` should own
reusable runtime implementation such as cluster bootstrap, storage
provisioning, ingress, secrets delivery, observability stacks, and other
cross-workload homelab concerns.

## Planned Repository Orientation

The planned repo structure favors `datasets/` over `warehouse/` because the canonical
durable artifact is analytical table state, not a shared mutable DuckDB database file.

See also:

- `docs/runtime_contract.md`
- `docs/data_lifecycle.md`
- `docs/storage_layout.md`
- `docs/data_dictionary.md`
- `docs/adr/adr-006-parquet-system-of-record.md`
- `docs/adr/adr-007-ducklake-canonical-table-format.md`
