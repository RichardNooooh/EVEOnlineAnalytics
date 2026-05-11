# Architecture

## Canonical Contract

The platform uses **DuckLake tables as the canonical analytical table contract**.

- **System of record:** DuckLake table state backed by Parquet data files.
- **Physical storage:** Parquet files stored on shared storage under the DuckLake table
  format.
- **Catalog state:** DuckLake catalog metadata is durable state and must be backed up
  with the data files. Production-style or mounted/shared deployments use PostgreSQL;
  local SQLite catalogs are for local smoke tests only.
- **Shared durable state:** DuckLake data files, catalog metadata, schema contracts,
  MLflow artifacts, and Airflow logs.
- **Compute state:** local or transient execution state such as DuckDB work databases.
- **Service boundary:** Kubernetes runs the application workloads, while PostgreSQL runs
  as an external infrastructure dependency on its own Proxmox VM.
- **Forbidden pattern:** no cluster-shared writable `.duckdb` file.
- **Guardrail:** mounted/shared DuckLake storage with a SQLite catalog is rejected.

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
  -> dbt reads canonical table state through a validated DuckLake/DuckDB handoff
  -> curated DuckLake tables and/or transient local DuckDB work DB
  -> ML training, dashboards, and APIs consume published table state
```

Ingestion source and pipeline code extracts and validates records; DuckLake destination
configuration and publication-specific storage/catalog policy live at the ingestion
publisher boundary.

For Everef ingestion, URL construction, source-date iteration, and HTTP probe metadata
belong to the canonical client module `ingest.clients.everef`. Market-history schema,
primary keys, and validation belong to `ingest.contracts.market_history`. The dlt source
should wire those boundaries together and stream chunks rather than own client behavior
or contract definitions.

## Local Development/Demo Runtime

The repository includes a local Docker Compose Airflow + dlt runtime for fast
iteration and portfolio demos without Proxmox, k3s, TrueNAS, or Helm.

This runtime is a development harness only. It is not production and does not replace
the canonical k3s + Helm architecture. Production workloads still target k3s, Helm,
TrueNAS-backed RWX storage for DuckLake data files, and the external Airflow metadata
PostgreSQL service described by ADR-018.

Local-to-production mapping:

- `.local/data` approximates TrueNAS NFS storage for DuckLake data files
- local Postgres approximates the Airflow metadata database
- bind-mounted DAGs and source code approximate the deployed Airflow image or DAG/code
  sync mechanism

Local smoke runs may use the default SQLite DuckLake catalog. Any run using mounted
DuckLake storage, including `--storage-target mounted` or an explicit mounted
`EVE_MARKET_DUCKLAKE_STORAGE`, must use a non-local catalog such as PostgreSQL through
`--ducklake-catalog` or `EVE_MARKET_DUCKLAKE_CATALOG`.

Local commands:

```bash
make local-airflow-up
make local-airflow-down
make local-airflow-reset
make local-pipeline-smoke
```

See `infra/local/README.md` for service and mount details.

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

## Scratch Storage Contract

Any DuckDB database used by dbt or batch jobs must live on local scratch storage.

Allowed examples:

- `emptyDir`
- node-local `ReadWriteOnce` PVC
- local developer filesystem

Disallowed example:

- RWX shared NFS volume containing a writable `.duckdb` file used by multiple pods

## Planned Repository Orientation

The planned repo structure favors `datasets/` over `warehouse/` because the canonical
durable artifact is analytical table state, not a shared mutable DuckDB database file.

See also:

- `docs/data_lifecycle.md`
- `docs/storage_layout.md`
- `docs/data_dictionary.md`
- `docs/adr/adr-016-parquet-system-of-record.md`
- `docs/adr/adr-020-ducklake-canonical-table-format.md`
