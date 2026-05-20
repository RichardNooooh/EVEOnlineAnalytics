# Transform

Standalone dbt project for curated analytics models. Commands below assume repo root.

## Local CLI

Use `uv` scoped to `transform/` and point dbt at committed project profile:

```bash
uv --project transform run dbt debug --project-dir transform --profiles-dir transform
uv --project transform run dbt parse --project-dir transform --profiles-dir transform
uv --project transform run dbt compile --project-dir transform --profiles-dir transform
```

Default local profile writes DuckDB work state to scratch path
`/tmp/eve_market_transform.duckdb`.

## Environment

- `DBT_DUCKDB_PATH`: local DuckDB work database path. Keep this on local or transient scratch.
- `DBT_THREADS`: dbt thread count. Defaults to `4`.
- `DBT_DATA_ROOT`: reserved for future mounted data-root wiring. Defaults to `/opt/eve-market/data`.

## Docker

Build local CLI image:

```bash
docker build -f transform/Dockerfile -t eve-market-transform:local transform
docker run --rm eve-market-transform:local --help
```

Container defaults:

- `DBT_PROFILES_DIR=/app`
- `DBT_PROJECT_DIR=/app`
- `DBT_DUCKDB_PATH=/tmp/eve_market_transform.duckdb`

## Current Boundary

This first pass sets up dbt project structure, local profile, and starter staging model.
It does not yet validate direct DuckLake-to-dbt source handoff.
