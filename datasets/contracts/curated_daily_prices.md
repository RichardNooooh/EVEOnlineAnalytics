# `curated_daily_prices`

## Purpose

BI-facing daily price mart published from
`transformation/models/marts/mart_curated_daily_prices.sql`.

This contract documents the first curated price publication used for local host-run
Evidence and other read-only analytical consumers.

## Publication Contract

- layer: curated
- dataset name: `curated_daily_prices`
- canonical table contract: DuckLake table backed by Parquet files
- expected shared path: `<data-root>/datasets/ducklake/curated/curated_daily_prices`
- writer: single dbt-driven curated publisher for target publication scope
- reader examples: Evidence BI, analytical ad hoc queries, downstream feature jobs

dbt builds candidate output in scratch DuckDB first. Readers consume this dataset only
after the curated publisher commits the validated table state into DuckLake.

## Grain And Keys

- grain: one row per `(date, region_id, type_id)`
- uniqueness expectation: no duplicate rows for `(date, region_id, type_id)`
- primary replacement scope: `date`
- common reader filters: `date`, `region_id`, `type_id`

## Upstream Inputs

- source publication: `raw.raw_market_history`
- intermediate curated fact: `fact_market_history`
- publishing model: `mart_curated_daily_prices`
- semantic dependency: ESI `average` is treated as VWAP, not median

## Columns

| Column | Type | Meaning |
|---|---|---|
| `date` | date | Observation date for market history row. |
| `region_id` | bigint | Market region identifier. |
| `type_id` | bigint | Item type identifier. |
| `vwap_price` | double | Daily volume-weighted average price. |
| `lowest` | double | Lowest observed price for `date`. |
| `highest` | double | Highest observed price for `date`. |
| `intraday_price_spread` | double | Derived as `highest - lowest`. |
| `intraday_volatility_ratio` | double | Derived as `(highest - lowest) / vwap_price` when `vwap_price > 0`. |
| `total_isk_traded` | double | Derived total ISK traded for market date. |

## Publication Steps

1. dbt reads published raw DuckLake state through attached `raw_lake` alias.
2. dbt builds `fact_market_history` and `mart_curated_daily_prices` in scratch DuckDB.
3. `eve-market-publish-curated` copies the validated mart into DuckLake curated state.
4. Evidence and other BI readers consume only published curated table state.

## Local BI Consumption

For supported local reviewer/demo flow, host-run Evidence should read this curated
DuckLake publication under repo-root `.local/data` or equivalent mounted shared root.
It should not read unpublished dbt scratch tables or a shared writable `.duckdb` file.

## Related Docs

- `docs/architecture.md`
- `docs/data_lifecycle.md`
- `docs/storage_layout.md`
- `docs/runtime_contract.md`
- `docs/data_dictionary.md`
