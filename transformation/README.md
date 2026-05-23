# Transformation

Standalone dbt project for curated analytics models. Commands below assume you are
already in `transformation/`.

## Local CLI

Use `uv run` and point dbt at committed project profile:

```bash
uv run dbt debug --profiles-dir .
uv run dbt parse --profiles-dir .
uv run dbt compile --profiles-dir .
```

Default local profile writes DuckDB work state to scratch path
`/tmp/eve_market_transform.duckdb`.

The same profile also attaches the local published DuckLake under repo-root
`.local/data` as a read-only source alias so dbt reads the canonical raw
publication instead of a shared writable `.duckdb` file.

The default host profile expects a standalone local SQLite publication under
repo-root `.local/data`. Plain host `eve-ingest ...` smoke runs from `ingestion/`
write under `ingestion/.local/`, so they do not populate that default
transformation/dbt source path. Reviewer-style local publications should come from the
Docker + Airflow stack under `infra/local/`, but host-side dbt then needs
`DBT_DUCKLAKE_*` overrides for the PostgreSQL-backed DuckLake catalog.

Populate reviewer-style local data through the Docker + Airflow path:

```bash
cp ../infra/local/.env.example ../infra/local/.env
make -C .. local-airflow-up
make -C .. ingestion-image
```

Then trigger the `backfill_market_history` DAG in Airflow so published DuckLake data
files land under repo-root `.local/data`.
When reading that reviewer-stack publication from host dbt, set
`DBT_DUCKLAKE_*` to the matching PostgreSQL-backed DuckLake target instead of
using the default local SQLite attach path.

## Environment

- `DBT_DUCKDB_PATH`: local DuckDB work database path. Keep this on local or transient scratch.
- `DBT_THREADS`: dbt thread count. Defaults to `4`.
- `DBT_DUCKLAKE_ALIAS`: attached DuckLake alias used by sources. Defaults to `raw_lake`.
- `DBT_DUCKLAKE_ATTACH_PATH`: DuckLake attach path. Local default is `ducklake:sqlite:../.local/data/datasets/ducklake/raw/raw_market_history/lake_catalog.sqlite` when commands run from `transformation/` against a standalone local SQLite publication.
- `DBT_DUCKLAKE_DATA_PATH`: DuckLake data path passed during attach. Local default is `../.local/data/datasets/ducklake/raw/raw_market_history/files` when commands run from `transformation/` against a standalone local SQLite publication.

Mounted/PostgreSQL-backed example:

```bash
export DBT_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=eve_market_ducklake host=postgres.example user=user password=password"
export DBT_DUCKLAKE_DATA_PATH="/opt/eve-market/data/datasets/ducklake/raw/raw_market_history"
uv run dbt debug --profiles-dir .
```

For PostgreSQL-backed DuckLake catalogs, `DBT_DUCKLAKE_DATA_PATH` should point at the
mounted dataset root rather than a local sqlite `files/` child.

If you want to point dbt at direct ingestion-local smoke output instead, override the
same variables explicitly:

```bash
export DBT_DUCKLAKE_ATTACH_PATH="ducklake:sqlite:../ingestion/.local/datasets/ducklake/raw/raw_market_history/lake_catalog.sqlite"
export DBT_DUCKLAKE_DATA_PATH="../ingestion/.local/datasets/ducklake/raw/raw_market_history/files"
uv run dbt debug --profiles-dir .
```

Local Airflow backfills use mounted storage plus a PostgreSQL DuckLake catalog inside
the compose runtime while publishing local files into repo-root `.local/data`. Use that
Docker + Airflow path when you want reviewer-style local data available for transform
work. The default host-side dbt CLI still expects a standalone local SQLite catalog, so
point it at the appropriate target with `DBT_DUCKLAKE_*` overrides when you are reading
either compose-published PostgreSQL-backed data or direct host ingestion smoke output.

Local smoke example:

```bash
uv run dbt debug --profiles-dir .
```

## Docker

Build local CLI image:

```bash
docker build -f Dockerfile -t eve-market-transform:local .
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

Example container smoke run with a bind mount from host local published data:

```bash
docker run --rm \
  -v "$PWD/../.local/data/datasets/ducklake/raw/raw_market_history:/app/ducklake/raw_market_history:ro" \
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
