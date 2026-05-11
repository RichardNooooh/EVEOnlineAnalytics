# Ingestion

Standalone Python project for source-specific ingestion while the wider repo is still
being assembled. The current implementation turns the Everef market history notebook
probe into reusable `dlt` code.

Commands below assume they are run from the repository root with `uv --project
ingestion`. If you are already in `ingestion/`, use `uv run` instead.

## Everef Market History

The Everef source lists expected daily CSV archives, probes each URL with `HEAD`, then
streams readable `.csv.bz2` files into `dlt` in pandas chunks.

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --dev-mode
```

By default, standalone CLI output uses DuckLake with a local SQLite catalog and local
DuckLake storage under `ingestion/.local/ducklake/everef_market_history`.

For Airflow or Kubernetes, mount the shared NFS PVC into the worker/pod and use the
mounted storage target:

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted
```

The mounted DuckLake storage target resolves to
`/opt/eve-market/data/ducklake/everef/market_history`. The workload must mount the
shared storage PVC at `/opt/eve-market/data` for this target to work.

Use `--data-root` to change the mounted storage root while keeping the standard
DuckLake storage path below it:

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted \
  --data-root /mnt/eve-market/data
```

Or set `EVE_MARKET_DATA_ROOT` for mounted workloads without changing command
arguments:

```bash
export EVE_MARKET_DATA_ROOT=/mnt/eve-market/data
```

Set `EVE_MARKET_DUCKLAKE_STORAGE` to override the selected DuckLake storage target
without changing command arguments:

```bash
export EVE_MARKET_DUCKLAKE_STORAGE=file:///opt/eve-market/data/ducklake/everef/market_history
```

Set `EVE_MARKET_DUCKLAKE_NAME` and `EVE_MARKET_DUCKLAKE_CATALOG` to override the
DuckLake attach name and catalog URL for scheduled workloads.

The same command can be run through the module entrypoint:

```bash
uv --project ingestion run python -m eve_market_ingestion.cli everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

Before loading each chunk, the source validates the expected market history contract:
required columns, non-null and unique `(date, region_id, type_id)` keys, source date
matching the CSV filename date, numeric values, non-negative numeric fields, and
`highest >= lowest`.

Useful options:

- `--pipeline-name`: dlt pipeline name, defaults to `everef_market_history`.
- `--dataset-name`: destination dataset/schema name, defaults to `everef_market_history`.
- `--destination`: dlt destination, defaults to `ducklake`.
- `--ducklake-name`: DuckLake attach name; overrides `EVE_MARKET_DUCKLAKE_NAME`, then defaults to `eve_market`.
- `--ducklake-catalog`: DuckLake catalog URL; overrides `EVE_MARKET_DUCKLAKE_CATALOG`, then defaults to the local SQLite catalog.
- `--storage-target`: DuckLake storage target, `local` or `mounted`, defaults to `local`.
- `--data-root`: mounted storage root used with `--storage-target mounted`; `EVE_MARKET_DATA_ROOT` is the environment fallback, then `/opt/eve-market/data`.
- `--ducklake-storage`: full DuckLake storage URL override. This overrides `EVE_MARKET_DUCKLAKE_STORAGE`, which overrides `--storage-target` and `--data-root` defaults.
- `--loader-file-format`: dlt loader file format, defaults to `parquet`.
- `--chunksize`: pandas CSV chunk size, defaults to `20000`.
- `--base-url`: override the Everef market history base URL for testing.

DuckLake storage URL precedence is explicit `--ducklake-storage`, then
`EVE_MARKET_DUCKLAKE_STORAGE`, then the selected `--storage-target` default. For
`mounted`, the default root is resolved from `--data-root`, then
`EVE_MARKET_DATA_ROOT`, then `/opt/eve-market/data`; for `local`, the SQLite catalog
and local DuckLake storage stay under
`ingestion/.local/ducklake/everef_market_history`. The mounted storage path is
`/opt/eve-market/data/ducklake/everef/market_history`.

Use a local SQLite DuckLake catalog for local development and smoke tests. Prefer a
PostgreSQL DuckLake catalog for production-style Airflow or Kubernetes deployments, with
DuckLake data files on mounted shared storage. Do not place a shared writable `.duckdb`
file on RWX/NFS.

DuckLake uses the DuckDB engine internally. If DuckDB is used for local experiments,
keep any writable `.duckdb` database on local or pod-scratch storage and never place a
shared writable `.duckdb` file on RWX/NFS.
