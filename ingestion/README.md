# Ingestion

Standalone Python project for source-specific ingestion. Commands below assume repo
root with `uv --project ingestion`. If you are already in `ingestion/`, use
`uv run` instead.

## Images

Ingestion image construction is automated by CLI and repo workflows. Manual builds
are still one command from repo root:

```bash
docker build -f ingestion/Dockerfile -t eve-market-ingestion:local ingestion
```

The container entrypoint is `eve-ingest`, so pass normal CLI args after the
image name.

## Airflow + Docker

Build or pull `eve-market-ingestion` first, then run normal CLI args in the
container. Example local-style run with raw sync included:

```bash
docker run --rm eve-market-ingestion:local everef run-pipeline \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --sync-raw \
  --dev-mode
```

For direct host execution with same defaults:

```bash
uv --project ingestion run eve-ingest everef run-pipeline \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --sync-raw
```

Default local output uses DuckLake storage under
`ingestion/.local/ducklake/everef_market_history` with local SQLite catalog.
When using the packaged host CLI, `dlt` runtime state stays repo-local under
`ingestion/.dlt/.var/<profile>/`, and local runtime artifacts stay under
`ingestion/.local/`.

## Airflow + Kubernetes

Mounted/shared DuckLake storage needs durable catalog such as PostgreSQL. Local
SQLite catalog is only for local smoke tests.

```bash
uv --project ingestion run eve-ingest everef run-pipeline \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted \
  --ducklake-catalog postgresql://user:password@postgres.example/eve_market_ducklake \
  --raw-ledger-url postgresql://user:password@postgres.example/eve_market_raw_files
```

Mounted storage resolves under `/opt/eve-market/data` by default. Workload must
mount shared storage there, or set `--data-root`.

Containerized Docker, Airflow, and Kubernetes runs should keep `dlt` runtime state on
explicit ephemeral scratch, separate from DuckLake durable storage and any shared
mounts. Current image defaults that scratch to `/scratch/dlt` for pipeline state and
`/scratch/local` for local runtime artifacts. Durable state remains DuckLake data plus
PostgreSQL-backed services.

Raw-file sync can also run as separate step before load:

```bash
uv --project ingestion run eve-ingest everef sync-raw-files \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted \
  --raw-ledger-url postgresql://user:password@postgres.example/eve_market_raw_files
```

## Useful Flags

- `--storage-target {local|mounted}`: choose local smoke-test paths or shared
  mounted storage layout.
- `--ducklake-catalog`: set DuckLake catalog URL. Use PostgreSQL for mounted/shared
  runs.
- `--raw-ledger-url`: set raw-file acquisition ledger URL. Required for mounted raw
  cache.
- `--data-root`: change mounted shared root from `/opt/eve-market/data`.
- `--sync-raw`: download changed raw files first, then load from raw cache.
- `--check-headers`: for raw sync, also inspect `content-length`, `last-modified`,
  and `ETag` in addition to `totals.json`.
- `--chunksize`: override pandas CSV chunk size when tuning memory or throughput.

## Guardrails

- Mounted/shared DuckLake storage needs PostgreSQL catalog.
- Local SQLite catalog is only for local development and smoke tests.
- Do not put shared writable `.duckdb` files on RWX/NFS storage.
- Host packaged CLI keeps repo-local `dlt` state under `ingestion/.dlt/.var/<profile>/`
  and `ingestion/.local/`; containerized runtimes should use `/scratch`-backed
  ephemeral scratch instead.
