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
a mutable SQLite file on NFS. Docker Compose and k3s/Airflow-style deployments use
PostgreSQL via `--raw-ledger-url`.

Containerized Docker, Airflow, and Kubernetes runs should use explicit ephemeral scratch
for `dlt` runtime state rather than shared NFS or DuckLake durable storage paths.

## Dataset Naming

Planned table naming convention:

- `raw_source_objects`
- `raw_market_history`
- `raw_market_orders`
- `raw_fuzzwork_orders`
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
│   │   ├── raw_market_orders/
│   │   └── raw_fuzzwork_orders/
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
- market order snapshot tables, including Fuzzwork order snapshots, partition by
  `source_market_date`
- curated tables partition by the smallest stable unit that supports rebuild and
  efficient downstream reads, typically `date` and optionally `region_id`
- current curated BI marts `curated_daily_prices` and `curated_trade_volume` use `date`
  as the primary replacement scope and retain `region_id` and `type_id` at row grain

## Write Semantics and Replacement Scope

Storage layout must preserve the difference between snapshot publication and
authoritative publication.

- snapshot-oriented datasets append new published observations over time and rely on
  idempotent insert-missing-key behavior to avoid duplicate publication of the same
  snapshot rows
- authoritative datasets define an explicit visible replacement scope, such as a source
  date partition or an entire table

Current raw dataset expectations:

- `raw_market_orders` and `raw_fuzzwork_orders` are snapshot-oriented datasets
- `raw_market_history` is authoritative for the source market date represented by each
  Everef daily file
- reference tables are authoritative latest extracts and replace the previously visible
  full-table contents when republished

This distinction matters for both physical organization and publication safety. A later
market-order snapshot should not be interpreted as a deletion set for earlier snapshots,
while a corrected market-history daily file must preserve its explicit date-level
publication boundary.

## Local BI Read Path

For the supported local reviewer/demo flow, Compose-run Evidence should read published
curated DuckLake state from repo-root `.local/data/datasets/ducklake/curated/` or an
equivalent mounted data root. Evidence is a read-only consumer of published curated
table state, not a writer and not a reader of dbt scratch DuckDB files.

## Manifest Contract

DuckLake catalog and table metadata are the primary publication boundary readers trust.
Supplemental manifests may record at least:

- dataset name
- publication timestamp
- writer identity or job reference
- publication mode or replacement class when useful for auditability
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

Future hardening may move containers to read-only root filesystems with explicit
scratch mounts; that does not change the durable storage layout above.
