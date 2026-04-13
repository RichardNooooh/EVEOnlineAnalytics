# Storage Layout

## Purpose

This document defines the planned shared-storage layout for the single-writer Parquet
architecture.

## Shared NFS Root

```text
/mnt/tank/eve-market/
├── datasets/
│   ├── raw/
│   ├── curated/
│   ├── manifests/
│   └── contracts/
├── mlflow/
└── airflow-logs/
```

`datasets/` is the durable analytical storage root.

## Dataset Naming

Planned dataset naming convention:

- `raw_market_history`
- `raw_market_orders`
- `curated_daily_prices`
- `curated_trade_volume`
- `feat_item_daily`

Use stable, descriptive names that reflect a published contract rather than an
implementation detail.

## Example Dataset Layout

```text
datasets/
├── raw/
│   ├── raw_market_history/
│   │   └── source=esi/region_id=10000002/date=2026-04-13/
│   └── raw_market_orders/
│       └── source=everef/region_id=10000002/snapshot_date=2026-04-13/
├── curated/
│   ├── curated_daily_prices/
│   └── feat_item_daily/
├── manifests/
│   └── <dataset-name>/
└── contracts/
    └── <dataset-name>.md
```

## Partitioning Guidance

Partitioning should be driven by reader and writer behavior.

Current planned rules:

- market history datasets partition by `source`, `region_id`, and `date`
- market order snapshot datasets partition by `source`, `region_id`, and snapshot time
  bucket such as `snapshot_date` or a timestamp partition
- curated datasets partition by the smallest stable unit that supports rebuild and
  efficient downstream reads, typically `date` and optionally `region_id`

## Manifest Contract

Each published dataset should eventually have a manifest that records at least:

- dataset name
- publication timestamp
- writer identity or job reference
- partition set included in the publication
- schema or contract version

The manifest is the publication boundary readers trust.

## Scratch Storage Is Separate

Scratch compute state is not part of the shared layout above.

- local DuckDB work DBs belong on pod-local scratch
- temporary publication paths must be treated as unpublished
- shared durable storage is only for published dataset state and supporting metadata
