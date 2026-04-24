# Architecture

## Canonical Contract

The platform uses a **single-writer Parquet architecture**.

- **System of record:** published Parquet datasets on shared NFS storage.
- **Shared durable state:** Parquet data files, dataset manifests, schema contracts,
  MLflow artifacts, and Airflow logs.
- **Compute state:** local or transient execution state such as DuckDB work databases.
- **Service boundary:** Kubernetes runs the application workloads, while PostgreSQL runs
  as an external infrastructure dependency on its own Proxmox VM.
- **Forbidden pattern:** no cluster-shared writable `.duckdb` file.

## Storage vs Compute

### Storage

Storage is durable, shared, and reader-visible.

- stored on TrueNAS NFS
- organized as Parquet datasets by layer and dataset name
- governed by publication manifests and contracts
- safe for many readers after publication

### Compute

Compute is local and disposable.

- DuckDB may be used for local development or single-writer batch jobs
- dbt may use a local DuckDB work database during execution
- compute outputs are not canonical until published to the dataset storage contract

## Planned Data Flow

```text
Airflow
  -> dataset writer / publisher
  -> raw or bronze Parquet datasets on shared NFS
  -> dbt reads Parquet-backed sources
  -> curated Parquet outputs and/or transient local DuckDB work DB
  -> ML training, dashboards, and APIs consume published datasets
```

## Local Development/Demo Runtime

The repository includes a local Docker Compose Airflow + dlt runtime for fast
iteration and portfolio demos without Proxmox, k3s, TrueNAS, or Helm.

This runtime is a development harness only. It is not production and does not replace
the canonical k3s + Helm architecture. Production workloads still target k3s, Helm,
TrueNAS-backed RWX storage for published datasets, and the external Airflow metadata
PostgreSQL service described by ADR-018.

Local-to-production mapping:

- `.local/data` approximates TrueNAS NFS dataset storage for published Parquet data
- local Postgres approximates the Airflow metadata database
- bind-mounted DAGs and source code approximate the deployed Airflow image or DAG/code
  sync mechanism

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

Future ingestion and transform jobs must use temp-write then promote semantics:

1. write candidate files into a temporary path
2. validate data and schema contract compliance
3. emit or update a manifest describing the promoted publication
4. promote the files into the canonical published location
5. only then allow downstream readers to treat the data as visible

This repository does not implement that behavior yet. This document defines the target
contract.

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
durable artifact is a published dataset, not a shared mutable database file.

See also:

- `docs/data_lifecycle.md`
- `docs/storage_layout.md`
- `docs/data_dictionary.md`
- `docs/adr/adr-016-parquet-system-of-record.md`
