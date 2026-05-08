# Ingestion

Standalone Python project for source-specific ingestion while the wider repo is still
being assembled. The current implementation turns the Everef market history notebook
probe into reusable `dlt` code.

## Everef Market History

The Everef source lists expected daily CSV archives, probes each URL with `HEAD`, then
streams readable `.csv.bz2` files into `dlt` in pandas chunks.

```bash
uv run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --dev-mode
```

By default, local filesystem output is written under
`ingestion/.local/dlt-staging/everef/market_history`.

For Airflow or Kubernetes, mount the shared NFS PVC into the worker/pod and use the
mounted storage target:

```bash
uv run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted
```

The mounted target resolves to
`/opt/eve-market/data/dlt-staging/everef/market_history`. The workload must mount the
shared storage PVC at `/opt/eve-market/data` for this target to work.

Use `--data-root` to change the mounted storage root while keeping the standard dlt
staging path below it:

```bash
uv run eve-market-ingest everef-market-history \
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

Set `EVE_MARKET_INGESTION_BUCKET_URL` to override the selected storage target without
changing command arguments:

```bash
export EVE_MARKET_INGESTION_BUCKET_URL=file:///opt/eve-market/data/dlt-staging/everef/market_history
```

The same command can be run through the module entrypoint:

```bash
uv run python -m eve_market_ingestion.cli everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

Useful options:

- `--pipeline-name`: dlt pipeline name, defaults to `everef_market_history`.
- `--dataset-name`: destination dataset/schema name, defaults to `everef_market_history`.
- `--destination`: dlt destination, defaults to `filesystem`.
- `--storage-target`: filesystem target, `local` or `mounted`, defaults to `local`.
- `--data-root`: mounted storage root used with `--storage-target mounted`; `EVE_MARKET_DATA_ROOT` is the environment fallback, then `/opt/eve-market/data`.
- `--bucket-url`: full filesystem destination URL override. This overrides `EVE_MARKET_INGESTION_BUCKET_URL`, which overrides `--storage-target` and `--data-root` defaults.
- `--loader-file-format`: dlt loader file format, defaults to `parquet`.
- `--chunksize`: pandas CSV chunk size, defaults to `20000`.
- `--base-url`: override the Everef market history base URL for testing.

Filesystem bucket URL precedence is explicit `--bucket-url`, then
`EVE_MARKET_INGESTION_BUCKET_URL`, then the selected `--storage-target` default. For
`mounted`, the default root is resolved from `--data-root`, then
`EVE_MARKET_DATA_ROOT`, then `/opt/eve-market/data`; for `local`, output stays under
`ingestion/.local/dlt-staging/everef/market_history`. The current `dlt` output is a
Parquet staging area; canonical dataset publication should validate and promote those
files into the shared storage contract with manifests. The market history table uses
`replace` writes so rerunning a scoped load does not imply unsupported filesystem
upserts.

DuckDB is not an ingestion dependency; if used for local experiments, keep the database
on local or pod-scratch storage and never place a shared writable `.duckdb` file on
RWX/NFS.
