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
`ingestion/.local/datasets/ducklake/raw/raw_market_history` with local SQLite
catalog.
When using the packaged host CLI, `dlt` runtime state stays repo-local under
`ingestion/.dlt/.var/<profile>/`, and local runtime artifacts stay under
`ingestion/.local/`.
This host-path output is for direct smoke testing only. The default transform/dbt
profile does not read from `ingestion/.local/`. If you want local data for the
reviewer-style transform flow, publish it through the local Docker + Airflow stack
under `infra/local/` instead of relying on the host CLI smoke path. Host-side dbt
may still need `DBT_DUCKLAKE_*` overrides when reading that PostgreSQL-backed
reviewer-stack publication.

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

Mounted storage resolves under
`/opt/eve-market/data/datasets/ducklake/raw/raw_market_history` by default.
Workload must mount shared storage there, or set `--data-root`.
In the local reviewer stack, this mounted path is backed by repo-root
`.local/data`, which is the local published-data file root used by the Docker +
Airflow reviewer flow.

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

## Rerun Note

Repeated `everef run-pipeline` executions for same date range are not currently a
no-op. Even when raw files are unchanged, `--sync-raw` still checks source
metadata and the load step still rereads cached CSVs and republishes affected
`date` partitions into DuckLake.

Possible future optimization: persist publication fingerprints for cached raw
inputs and skip reruns whose requested date range is already published from the
same raw-file content.

## Guardrails

- Mounted/shared DuckLake storage needs PostgreSQL catalog.
- Local SQLite catalog is only for local development and smoke tests.
- Do not put shared writable `.duckdb` files on RWX/NFS storage.
- Host packaged CLI keeps repo-local `dlt` state under `ingestion/.dlt/.var/<profile>/`
  and `ingestion/.local/`; containerized runtimes should use `/scratch`-backed
  ephemeral scratch instead.
- If you want local reviewer-stack data for transform work, publish it through the
  local Docker + Airflow path rather than the host CLI smoke path.
