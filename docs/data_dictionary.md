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

- region identifier
- type identifier
- observation date
- one row per `(date, region_id, type_id)`; each Everef daily source file must contain
  only rows for its source market date
- source fields preserved with documented semantic quirks
- publication metadata recorded through DuckLake catalog state, contracts, and
  supplemental manifests where useful
- dataset class is source-date-authoritative
- current publication behavior uses assert-partition-coverage plus insert-missing
  semantics for each source market date

### `raw_market_orders`

Durable DuckLake-backed representation of market order snapshots.

Expected contract elements:

- region identifier
- snapshot timestamp
- buy or sell side flags
- price, volume, range, and location fields from the source snapshot
- dataset class is snapshot-oriented
- publication behavior uses idempotent insert-missing-key semantics so replay of the
  same snapshot does not duplicate rows

The same snapshot-oriented publication model also applies to `raw_fuzzwork_orders`.

### Reference Tables

Reference tables such as item types, regions, groups, and categories are published from
latest full extracts.

Expected contract elements:

- stable natural keys such as `type_id`, `region_id`, `group_id`, or `category_id`
- latest-extract-authoritative semantics
- publication behavior uses full-table replacement semantics per reference table

## Curated Dataset Contracts

Curated datasets standardize naming, grain, and derivations for analytics and ML.

### `curated_daily_prices`

Current implemented curated price mart for BI publication.

Contract highlights:

- grain is one row per `(date, region_id, type_id)`
- `vwap_price` carries forward ESI `average` semantics as VWAP
- `intraday_price_spread` is derived as `highest - lowest`
- `intraday_volatility_ratio` is derived as `(highest - lowest) / vwap_price` when
  `vwap_price > 0`
- published contract lives at `../datasets/contracts/curated_daily_prices.md`

### `curated_trade_volume`

Current implemented curated trade-volume mart for BI publication.

Contract highlights:

- grain is one row per `(date, region_id, type_id)`
- `traded_units` carries forward staged daily volume
- `total_isk_traded` is derived as `volume * average` in upstream `fact_market_history`
- `average_isk_per_order` is derived as `total_isk_traded / order_count` when
  `order_count > 0`, else `0`
- published contract lives at `../datasets/contracts/curated_trade_volume.md`

## Publication Contract Notes

- DuckLake tables are the system of record
- Parquet files are the physical storage format below DuckLake
- schemas should be versioned through contracts and supplemental manifests
- dbt and batch compute may use transient local DuckDB state, but that state is not
  canonical storage
