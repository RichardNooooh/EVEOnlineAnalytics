# transformation/AGENTS.md

Read this when changing dbt configuration, SQL models, seeds, macros, analyses, tests,
or ML feature transforms.

## Read First

- `../AGENTS.md`
- `../datasets/AGENTS.md`
- `../docs/data_lifecycle.md`
- `../docs/data_dictionary.md`
- `../docs/storage_layout.md`

## dbt Rules

- Use lowercase SQL keywords.
- Prefer CTEs over subqueries.
- Keep one model per file.
- Use descriptive prefixes: `stg_`, `int_`, `fact_`, `dim_`, `mart_`, and `feat_`.
- Prefer schema YAML tests or `tests/` when adding dbt tests.
- Any DuckDB work database used by dbt must live on local or transient scratch, never
  shared RWX NFS.

## Model Layers

- `models/staging/everef/`: source-shaped everef cleanup and typing.
- `models/staging/esi/`: source-shaped ESI cleanup and typing.
- `models/intermediate/`: reusable joins and derived entities.
- `models/marts/`: BI-facing analytical models, including `fact_`, `dim_`, and denormalized `mart_` outputs.
- `models/ml_features/`: ML-facing feature contracts.

## ML Feature Targets

- Rolling 7d, 14d, and 30d price and volume statistics.
- Price volatility as `(highest - lowest) / average`.
- Volume z-score relative to trailing 30d windows.
- Cross-region price divergence.
- Order count / volume ratio as market-depth proxy.
- Temporal features such as day-of-week and days-since-last-patch.

## Source Semantics

- ESI market history `average` is VWAP.
- Avoid deriving model names or docs that imply the API `average` field is median.
