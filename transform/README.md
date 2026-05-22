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

The same profile also attaches the ingestion DuckLake as a read-only source alias so
dbt reads the canonical raw publication instead of a shared writable `.duckdb` file.

## Environment

- `DBT_DUCKDB_PATH`: local DuckDB work database path. Keep this on local or transient scratch.
- `DBT_THREADS`: dbt thread count. Defaults to `4`.
- `DBT_DUCKLAKE_ALIAS`: attached DuckLake alias used by sources. Defaults to `raw_lake`.
- `DBT_DUCKLAKE_ATTACH_PATH`: DuckLake attach path. Local default is `ducklake:sqlite:ingestion/.local/datasets/ducklake/raw/raw_market_history/lake_catalog.sqlite` when commands run from repo root.
- `DBT_DUCKLAKE_DATA_PATH`: DuckLake data path passed during attach. Local default is `ingestion/.local/datasets/ducklake/raw/raw_market_history/files` when commands run from repo root.

Mounted/PostgreSQL-backed example:

```bash
export DBT_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=eve_market_ducklake host=postgres.example user=user password=password"
export DBT_DUCKLAKE_DATA_PATH="/opt/eve-market/data/datasets/ducklake/raw/raw_market_history"
uv --project transform run dbt debug --project-dir transform --profiles-dir transform
```

Local smoke example:

```bash
uv --project transform run dbt debug --project-dir transform --profiles-dir transform
```

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
- `DBT_DUCKLAKE_ALIAS=raw_lake`
- `DBT_DUCKLAKE_ATTACH_PATH=ducklake:sqlite:/app/ducklake/raw_market_history/lake_catalog.sqlite`
- `DBT_DUCKLAKE_DATA_PATH=/app/ducklake/raw_market_history/files`

The transform image does not bundle ingestion output. To make the default container
attach work, mount the DuckLake catalog and files at `/app/ducklake/raw_market_history`.
Otherwise override `DBT_DUCKLAKE_ATTACH_PATH` and `DBT_DUCKLAKE_DATA_PATH` to a mounted
DuckLake location, such as a PostgreSQL-backed shared deployment.

Example container smoke run with a bind mount from host local ingestion output:

```bash
docker run --rm \
  -v "$PWD/ingestion/.local/datasets/ducklake/raw/raw_market_history:/app/ducklake/raw_market_history:ro" \
  eve-market-transform:local debug
```

Example container run against mounted/PostgreSQL-backed DuckLake:

```bash
docker run --rm \
  -e DBT_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=eve_market_ducklake host=postgres.example user=user password=password" \
  -e DBT_DUCKLAKE_DATA_PATH="/opt/eve-market/data/datasets/ducklake/raw/raw_market_history" \
  -v /opt/eve-market/data:/opt/eve-market/data:ro \
  eve-market-transform:local debug
```

## Current Boundary

This profile now reads `raw.raw_market_history` through the attached DuckLake alias
`raw_lake` while keeping dbt materializations on local scratch DuckDB.
