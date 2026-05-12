# Data Dictionary

## Purpose

This document captures source-level field contracts and the planned DuckLake-backed
publishing model.

## Source: ESI Market History

Fields returned by `GET /markets/{region_id}/history/?type_id={type_id}`:

| Field | Type | Notes |
|---|---|---|
| `average` | numeric | Volume-weighted average price (VWAP), despite in-game client median labeling |
| `date` | date | Observation date |
| `highest` | numeric | Highest observed price |
| `lowest` | numeric | Lowest observed price |
| `order_count` | integer | Count of market orders |
| `volume` | integer | Traded volume |

## Critical Quirk

The ESI `average` field should be documented as a **volume-weighted average price
(VWAP)** throughout the project. The in-game client labels the corresponding value as
`median`, but this project treats the API field semantics as VWAP. See
`experiments/esi-average-field-validation/` for the Gleaned Static sample that
validates `average = total ISK traded / total units traded` on low-volume rows.

## Planned Raw Dataset Contracts

### `raw_market_history`

Durable Parquet representation of source market history records.

Expected contract elements:

- source identifier
- region identifier
- type identifier
- observation date
- one row per `(date, region_id, type_id)`; each Everef daily source file must contain
  only rows for its source market date
- source fields preserved with documented semantic quirks
- publication metadata recorded through DuckLake catalog state, contracts, and
  supplemental manifests where useful

### `raw_market_orders`

Durable DuckLake-backed representation of market order snapshots.

Expected contract elements:

- source identifier
- region identifier
- snapshot timestamp
- buy or sell side flags
- price, volume, range, and location fields from the source snapshot

## Planned Curated Dataset Contracts

Curated datasets will standardize naming, grain, and derivations for analytics and ML.

Examples:

- `curated_daily_prices`
- `curated_trade_volume`
- `curated_regional_spreads`
- `feat_item_daily`

## Publication Contract Notes

- DuckLake tables are the system of record
- Parquet files are the physical storage format below DuckLake
- schemas should be versioned through contracts and supplemental manifests
- dbt and batch compute may use transient local DuckDB state, but that state is not
  canonical storage
