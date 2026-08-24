# Transformation

Standalone dbt project for curated analytics models. Commands below assume you are
already in `transformation/`.

## Local CLI

Supported local exception: run dbt on host while it attaches to local Compose
PostgreSQL-backed DuckLake catalogs.

Use `uv run` and point dbt at committed project profile:

```bash
uv run dbt debug --profiles-dir .
uv run dbt parse --profiles-dir .
uv run dbt compile --profiles-dir .
```

Default local profile writes DuckDB work state to scratch path
`/tmp/eve_market_transform.duckdb`.

The Python `duckdb` package used by `dbt-duckdb` does not provide the standalone
DuckDB CLI binary. Mise manages the CLI for this project.

The same profile attaches the local Compose-published raw DuckLake under repo-root
`.local/data` through PostgreSQL-backed DuckLake catalog metadata so dbt reads the
canonical raw publication instead of a shared writable `.duckdb` file.

The profile also attaches writable curated DuckLake. dbt still keeps staging,
intermediate, and fact compute in the local scratch DuckDB database, but final published
mart models materialize directly into curated DuckLake tables.

This means curated tables become visible when model materialization finishes. dbt data
tests still run after those table writes, so this workflow does not provide a
pre-visibility validation barrier.

For the local Compose harness, `mise run transform:build` prepares mounted data
permissions before running the supported host `dbt build`.

Populate reviewer-style local data through Docker Compose + Airflow path:

```bash
cp ../infra/local/.env.example ../infra/local/.env
mise run airflow:up
mise run ingestion:image
```

Then trigger the `backfill_market_history` DAG in Airflow so published DuckLake data
files land under repo-root `.local/data`.
The local Compose stack also exposes its Postgres catalog on the host by default
at `127.0.0.1:5432` as supported host-dbt exception, so host dbt can attach
directly to that PostgreSQL-backed DuckLake catalog.

## Environment

- `DBT_DUCKDB_PATH`: local DuckDB work database path. Keep this on local or transient scratch.
- `DBT_THREADS`: dbt thread count. Defaults to `4`.
- `DBT_POSTGRES_HOST`: Postgres host used by the default local attach string. Defaults to `127.0.0.1`.
- `DBT_DUCKLAKE_ALIAS`: attached DuckLake alias used by sources. Defaults to `raw_lake`.
- `DBT_DUCKLAKE_ATTACH_PATH`: DuckLake attach path. Local default targets Compose PostgreSQL on `127.0.0.1:5432` for supported host-dbt workflow using `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_HOST_PORT` defaults.
- `DBT_DUCKLAKE_DATA_PATH`: DuckLake data path passed during attach. Local default is `../.local/data/datasets/ducklake/raw`.
- `DBT_DUCKLAKE_METADATA_SCHEMA`: DuckLake metadata schema inside the catalog database. Defaults to `eve_market`.
- `DBT_DUCKLAKE_OVERRIDE_DATA_PATH`: Override the catalog's stored data path for the current connection. Use `0` or `1`. Defaults to `1` because the local catalog stores the container path.
- `CURATED_DUCKLAKE_ATTACH_PATH`: Writable curated DuckLake attach path used by final published mart models. Defaults to local Compose PostgreSQL on `127.0.0.1:5432` for supported host-dbt workflow.
- `CURATED_DUCKLAKE_DATA_PATH`: Curated DuckLake data root. Defaults to `../.local/data/datasets/ducklake` so published tables land under `curated/`.
- `CURATED_DUCKLAKE_ALIAS`: Writable curated DuckLake alias. Defaults to `curated_lake`.
- `CURATED_DUCKLAKE_SCHEMA`: Curated DuckLake schema. Defaults to `curated`.
- `CURATED_DUCKLAKE_METADATA_SCHEMA`: Curated DuckLake metadata schema. Defaults to `eve_market`.
- `CURATED_DUCKLAKE_OVERRIDE_DATA_PATH`: Override the curated catalog's stored data path for the current connection. Use `0` or `1`. Defaults to `1` because the local catalog stores the container path.

Mounted/PostgreSQL-backed example:

```bash
export DBT_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=eve_market_ducklake host=postgres.example user=user password=password"
export DBT_DUCKLAKE_DATA_PATH="/opt/eve-market/data/datasets/ducklake/raw"
export CURATED_DUCKLAKE_ATTACH_PATH="ducklake:postgres:dbname=eve_market_ducklake host=postgres.example user=user password=password"
export CURATED_DUCKLAKE_DATA_PATH="/opt/eve-market/data/datasets/ducklake"
uv run dbt debug --profiles-dir .
```

For PostgreSQL-backed DuckLake catalogs, `DBT_DUCKLAKE_DATA_PATH` should point at the
mounted dataset root rather than a local sqlite `files/` child.

Local Airflow backfills use mounted storage plus a PostgreSQL DuckLake catalog inside
the Compose runtime while publishing local files into repo-root `.local/data`. Use that
Compose + Airflow path when you want reviewer-style local data available for transform
work.

For copy-pasteable supported host-dbt local Compose example, see
`dbt-airflow-local.env.example.sh`.
That helper also creates the local curated DuckLake schema directory before first write.
If local Compose created `.local/data` with container-owned permissions, run
`mise run transform:build` from the repository root. From `transformation/` you can
also run individual dbt commands:

```bash
source ./dbt-airflow-local.env.example.sh
uv run dbt debug --profiles-dir .
uv run dbt parse --profiles-dir .
uv run dbt compile --profiles-dir .
uv run dbt build --profiles-dir .
```

## DuckDB Inspection

Use the recommended in-memory inspection shell from any project directory:

```bash
mise run duckdb:connect
```

It loads `infra/local/.env` and attaches the local PostgreSQL-backed publications
read-only as `raw_lake` and `curated_lake`. The task exits clearly if the local
catalog is unavailable. `curated_lake` contains curated tables only after
`mise run transform:build` completes. Useful first queries:

```sql
show databases;
show all tables;
select count(*) from raw_lake.raw.raw_market_history;
select * from curated_lake.curated.curated_daily_prices limit 5;
```

`/tmp/eve_market_transform.duckdb` remains dbt's local scratch state, not the
recommended publication-inspection database. Open it directly only when inspecting
dbt's transient staging, intermediate, or fact relations.

If `5432` is already in use on your host, set `POSTGRES_HOST_PORT` in
`infra/local/.env` and export matching `POSTGRES_HOST_PORT` or `DBT_DUCKLAKE_ATTACH_PATH`
before running dbt.

Current first-pass curated outputs:

- `curated.curated_daily_prices` from `mart_curated_daily_prices`
- `curated.curated_trade_volume` from `mart_curated_trade_volume`

## Current Boundary

This profile reads `raw.raw_market_history` through the attached DuckLake alias
`raw_lake` while keeping dbt staging, intermediate, and fact materializations on local
scratch DuckDB. Final curated BI marts materialize directly into writable DuckLake
tables on the attached `curated_lake` alias.
