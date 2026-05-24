# Storage Layout

## Purpose

This document defines the storage contract required by
`eve-market-analytics`. It describes durable shared-data layout,
publication-visible paths, and scratch-storage separation that any runtime must
preserve. Reusable NFS exports, Kubernetes storage classes, mount wiring,
backup automation, and other platform implementation details belong to the
companion `homelab-data-platform` repository.

## Example Shared Runtime Root

```text
<shared-data-root>/
├── datasets/
│   ├── ducklake/
│   │   ├── raw/
│   │   └── curated/
│   ├── manifests/
│   └── contracts/
├── raw/
│   └── <source>/<dataset>/
├── mlflow/
└── airflow-logs/
```

`datasets/ducklake/` is the durable analytical data-file root. In production-style or
mounted/shared deployments, the DuckLake catalog must use non-local durable storage such
as PostgreSQL. A local SQLite DuckLake catalog is only for local smoke tests, and mounted
DuckLake storage with a SQLite catalog is rejected.

Ingestion resolves DuckLake storage from explicit `--ducklake-storage`, then the
selected storage target. The mounted target uses the shared data root and requires a
PostgreSQL-style catalog from `--ducklake-catalog`.

The exact mechanism used to provision or mount this storage is intentionally
out of scope here. This repo defines workload-visible layout and invariants;
`homelab-data-platform` should implement the reusable runtime that satisfies
them.

`raw/` stores cached source files before dlt publication. Its acquisition ledger is not
a shared SQLite file on NFS. Direct local ingestion defaults to a local SQLite ledger,
while Docker Compose and k3s/Airflow-style deployments use PostgreSQL via
`--raw-ledger-url`.

The packaged host ingestion CLI keeps `dlt` runtime state repo-local under
`ingestion/.dlt/.var/<profile>/` and `ingestion/.local/`. Containerized Docker,
Airflow, and Kubernetes runs should use explicit ephemeral scratch for `dlt` runtime
state rather than shared NFS or DuckLake durable storage paths. Direct host CLI smoke
output under `ingestion/.local/` is separate from the local reviewer-stack publication
path under repo-root `.local/data`.

## Dataset Naming

Planned table naming convention:

- `raw_market_history`
- `raw_market_orders`
- `curated_daily_prices`
- `curated_trade_volume`
- `feat_item_daily`

Use stable, descriptive names that reflect a published table contract rather than an
implementation detail.

## Example Dataset Layout

```text
datasets/
├── ducklake/
│   ├── raw/
│   │   ├── raw_market_history/
│   │   └── raw_market_orders/
│   └── curated/
│       ├── curated_daily_prices/
│       ├── curated_trade_volume/
│       └── feat_item_daily/
├── manifests/
│   └── <dataset-name>/
└── contracts/
    └── <dataset-name>.md
```

This path structure is a workload contract, not a requirement that every
environment expose the same underlying host paths verbatim. Local and shared
runtimes may differ in implementation as long as they preserve equivalent
durable roots, publication boundaries, and scratch versus durable separation.

## Partitioning Guidance

Table partitioning and replacement scope should be driven by reader and writer behavior.

Current planned rules:

- market history tables use `date` as the primary Everef replacement scope and include
  `region_id` and `type_id`
- market order snapshot tables partition by `region_id` and snapshot time
  bucket such as `snapshot_date` or a timestamp partition
- curated tables partition by the smallest stable unit that supports rebuild and
  efficient downstream reads, typically `date` and optionally `region_id`
- current curated BI marts `curated_daily_prices` and `curated_trade_volume` use `date`
  as the primary replacement scope and retain `region_id` and `type_id` at row grain

## Local BI Read Path

For the supported local reviewer/demo flow, host-run Evidence should read published
curated DuckLake state from repo-root `.local/data/datasets/ducklake/curated/` or an
equivalent mounted data root. Evidence is a read-only consumer of published curated
table state, not a writer and not a reader of dbt scratch DuckDB files.

## Manifest Contract

DuckLake catalog and table metadata are the primary publication boundary readers trust.
Supplemental manifests may record at least:

- dataset name
- publication timestamp
- writer identity or job reference
- partition set included in the publication
- schema or contract version

The manifest is supporting metadata, not a replacement for DuckLake catalog state.

## Scratch Storage Is Separate

Scratch compute state is not part of the shared layout above.

This separation is a hard workload requirement so platform reuse does not blur
durable analytical state with container-local or job-local execution state.

- local DuckDB work DBs belong on pod-local scratch
- `dlt` runtime state for containerized runs belongs on explicit ephemeral scratch
- temporary publication paths must be treated as unpublished
- shared durable storage is only for published table data files and supporting metadata
- SQLite DuckLake catalogs belong only to local smoke storage, not mounted/shared
  DuckLake storage

Future hardening may move containers to read-only root filesystems with explicit
scratch mounts; that does not change the durable storage layout above.
