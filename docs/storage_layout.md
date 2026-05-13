# Storage Layout

## Purpose

This document defines the planned shared-storage layout for DuckLake tables backed by
Parquet data files.

## Shared NFS Root

```text
/mnt/tank/eve-market/
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

Ingestion resolves DuckLake storage from explicit `--ducklake-storage`, then
`EVE_MARKET_DUCKLAKE_STORAGE`, then the selected storage target. The mounted target uses
the shared data root and requires a PostgreSQL-style catalog from `--ducklake-catalog` or
`EVE_MARKET_DUCKLAKE_CATALOG`.

`raw/` stores cached source files before dlt publication. Its acquisition ledger is not
a shared SQLite file on NFS. Direct local ingestion defaults to a local SQLite ledger,
while Docker Compose and k3s/Airflow-style deployments use PostgreSQL via
`EVE_MARKET_RAW_FILES_LEDGER_URL`.

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
│       └── feat_item_daily/
├── manifests/
│   └── <dataset-name>/
└── contracts/
    └── <dataset-name>.md
```

## Partitioning Guidance

Table partitioning and replacement scope should be driven by reader and writer behavior.

Current planned rules:

- market history tables use `date` as the primary Everef replacement scope and include
  `source`, `region_id`, and `type_id`
- market order snapshot tables partition by `source`, `region_id`, and snapshot time
  bucket such as `snapshot_date` or a timestamp partition
- curated tables partition by the smallest stable unit that supports rebuild and
  efficient downstream reads, typically `date` and optionally `region_id`

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

- local DuckDB work DBs belong on pod-local scratch
- temporary publication paths must be treated as unpublished
- shared durable storage is only for published table data files and supporting metadata
- SQLite DuckLake catalogs belong only to local smoke storage, not mounted/shared
  DuckLake storage
