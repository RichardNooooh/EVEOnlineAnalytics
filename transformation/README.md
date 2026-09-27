# Transformation

Standalone dbt project for curated analytics models. Commands below assume you are
already in `transformation/`.

## Forge Study Panel

`seeds/forge_study_panel.csv` freezes accepted membership with only `type_id` and
`study_category`. The selection notebook generates it from the selected IDs and
explicit manual category assignments when its export cell runs. Review generated
changes and rebuild dbt before analyzing panel history. Selection semantics are in
[`docs/data_dictionary.md`](../docs/data_dictionary.md#frozen-forge-study-panel).

`int_study_panel` adds authoritative names, and `int_study_panel_history` joins the
accepted panel to observed Forge history. Run `mise run transform:build` from the
repository root before executing the notebook's membership/history sections.

## SQL Linting

Use `.sqlfluff` for fast local Jinja linting and formatting. `.sqlfluff.dbt` is
the authoritative dbt-templated configuration used by CI. Run from
`transformation/`:

```bash
uv run sqlfluff fix . --ignore-local-config --config .sqlfluff
uv run sqlfluff lint . --ignore-local-config --config .sqlfluff
uv run sqlfluff lint . --ignore-local-config --config .sqlfluff.dbt
```

## Local CLI

Supported local exception: run dbt on host while it attaches to local Compose
PostgreSQL-backed DuckLake catalogs.

Use `uv run` and point dbt at committed project profile:

```bash
uv run dbt deps --profiles-dir .
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
- `DBT_DUCKLAKE_ATTACH_PATH`: DuckLake attach path. Unless explicitly set, the local default uses `POSTGRES_DB`, `DBT_POSTGRES_HOST`, `POSTGRES_HOST_PORT`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` (with their local defaults) for the supported host-dbt workflow.
- `DBT_DUCKLAKE_DATA_PATH`: DuckLake data path passed during attach. Local default is `../.local/data/datasets/ducklake/raw`.
- `DBT_DUCKLAKE_METADATA_SCHEMA`: DuckLake metadata schema inside the catalog database. Defaults to `eve_market`.
- `DBT_DUCKLAKE_OVERRIDE_DATA_PATH`: Override the catalog's stored data path for the current connection. Use `0` or `1`. Defaults to `1` because the local catalog stores the container path.
- `CURATED_DUCKLAKE_ATTACH_PATH`: Writable curated DuckLake attach path used by final published mart models. Unless explicitly set, the local default uses the same PostgreSQL environment values as `DBT_DUCKLAKE_ATTACH_PATH`.
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
All local materializing builds must use `mise run transform:build` from the
repository root so the shared curated writer lock is held. Direct commands from
`transformation/` are limited to non-materializing operations such as debug, parse,
compile, and the metadata-only codegen operations documented below:

```bash
source ./dbt-airflow-local.env.example.sh
uv run dbt debug --profiles-dir .
uv run dbt parse --profiles-dir .
uv run dbt compile --profiles-dir .
```

## YAML Scaffolding and Documentation

[`dbt-codegen`](https://github.com/dbt-labs/dbt-codegen) is pinned in
`packages.yml`; `package-lock.yml` also locks its transitive dependencies. Run
`uv run dbt deps --profiles-dir .` after checkout or a dependency change. CI and
the transformation image install these packages as part of their setup.

After loading the local environment as above, generate a source scaffold from
the attached raw DuckLake catalog:

```bash
uv run dbt run-operation generate_source --profiles-dir . --args "{
  \"database_name\": \"${DBT_DUCKLAKE_ALIAS:-raw_lake}\",
  \"schema_name\": \"raw\",
  \"name\": \"everef\",
  \"table_names\": [\"raw_market_history\"],
  \"generate_columns\": true,
  \"include_descriptions\": true,
  \"include_database\": true,
  \"include_schema\": true
}"
```

Generate model properties from an existing materialized relation:

```bash
uv run dbt run-operation generate_model_yaml --profiles-dir . --args '{
  "model_names": ["stg_everef_market_history"],
  "upstream_descriptions": true
}'
```

These operations read relation metadata and print YAML; they do not build models
or maintain documentation automatically. Source tables must exist, and model
columns reflect the last materialized relation, not unbuilt SQL edits. If a model
needs materializing, use the supported `mise run transform:build` task from the
repository root before generating its scaffold.

Review and merge the printed scaffold into the existing properties files. Preserve
the environment-driven source database configuration, curated descriptions, and
existing tests rather than replacing an entire file with generated output.
`upstream_descriptions` matches identical column names in direct upstream nodes;
it does not trace SQL aliases or verify that a same-named column has the same
meaning. For example, `average as vwap_price` needs an explicit description.

Model and source YAML document column types, grain, units, derivations, and
publication semantics. Raw types follow the ingestion table definitions in
`../ingestion/eve_ingest/ducklake/raw_tables.py`; model types follow their SQL
casts and output expressions. `data_type` is descriptive metadata here, not an
enforced dbt model contract. For semantic context, see the
[data dictionary](../docs/data_dictionary.md) and
[data lifecycle](../docs/data_lifecycle.md).

Validate edited properties with:

```bash
uv run dbt parse --profiles-dir . --no-partial-parse
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

The shell also honors a readable `~/.duckdbrc`; Mise incorporates it into the
protected init file before attaching the local publications.

## Cleanup

Run `mise run duckdb:cleanup` from the repository root to remove untracked dbt
relations. It prepares supported local storage permissions, sources the local dbt
environment, displays a dry-run, and applies only after you type `apply` at the
prompt. It holds the shared local curated-writer lock throughout those steps;
`mise run transform:build` uses that same lock. Cancellation makes no changes.

Cleanup considers dbt scratch `main` and published `curated` relations only; raw
relations are excluded. It supports deleting tables and views, reports unknown
relation types without deleting them, and limits each execution to 20 drops. The
apply run recomputes candidates after confirmation.

Direct `cleanup_untracked_relations` apply calls must pass
`curated_writer_lock_held: true` after the caller has established single-writer
serialization. This argument is a guard and contract; it does not prove a lock is held.

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
