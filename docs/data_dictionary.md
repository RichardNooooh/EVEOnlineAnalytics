# Data Dictionary

## Purpose

This document captures source-level field contracts and the planned dataset-oriented
publishing model.

## Source: ESI Market History

Fields returned by `GET /markets/{region_id}/history/?type_id={type_id}`:

| Field | Type | Notes |
|---|---|---|
| `average` | numeric | Actually the source median, not the arithmetic mean |
| `date` | date | Observation date |
| `highest` | numeric | Highest observed price |
| `lowest` | numeric | Lowest observed price |
| `order_count` | integer | Count of market orders |
| `volume` | integer | Traded volume |

## Critical Quirk

The ESI `average` field is a known source bug and should be documented as the **median**
throughout the project.

## Planned Raw Dataset Contracts

### `raw_market_history`

Durable Parquet representation of source market history records.

Expected contract elements:

- source identifier
- region identifier
- type identifier
- observation date
- source fields preserved with documented semantic quirks
- publication metadata recorded in manifests rather than requiring a mutable database

### `raw_market_orders`

Durable Parquet representation of market order snapshots.

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

- published Parquet datasets are the system of record
- schemas should be versioned through contracts and manifests
- dbt and batch compute may use transient local DuckDB state, but that state is not
  canonical storage
