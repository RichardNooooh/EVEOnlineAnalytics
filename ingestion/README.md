# Ingestion

Standalone Python project for source-specific ingestion while the wider repo is still
being assembled. The current implementation turns the Everef market history notebook
probe into reusable `dlt` code.

Commands below assume they are run from the repository root with `uv --project
ingestion`. If you are already in `ingestion/`, use `uv run` instead.

## Implementation Boundaries

Everef ingestion keeps source concerns split across small modules:

- `ingest.clients.everef` is the canonical Everef client boundary. Import URL
  construction, date iteration, and HTTP probe metadata helpers from this module.
- `ingest.contracts.market_history` owns market-history schema, primary keys, and
  chunk validation. The `average` field is documented there as volume-weighted average
  price (VWAP), not median.
- `ingest.sources.everef` defines the `dlt` source/resources and stays thin: it wires
  client URL/probe behavior, contract schema/validation, and CSV chunk streaming.
- `ingest.raw_files.publisher` owns generic raw cached-file publication through
  `RawFileSpec` and `publish_raw_file`: cache-hit checks, downloads, checksums,
  ledger inserts, failed-acquisition rows, and old-copy pruning.
- `ingest.raw_files.repository` owns the URL-selected SQLite or PostgreSQL raw-file
  acquisition ledger.
- `ingest.raw_files.everef` is the Everef-specific adapter. It probes Everef files,
  converts source metadata into `RawFileSpec`, and lists cached Everef files for dlt.
- `ingest.publishers.*` owns destination configuration, storage/catalog precedence, and
  mounted-storage guardrails.

Do not import from removed compatibility shims; use the canonical module paths above.

## Everef Market History

The Everef source lists expected daily CSV archives, probes each URL with `HEAD`, then
streams readable `.csv.bz2` files into `dlt` in pandas chunks. By default, the CLI now
loads from raw cache and raises `FileNotFoundError` if expected raw files were not
synced yet. Raw source-file acquisition is available as a separate cache step backed by
SQLite for direct local runs or PostgreSQL for deployed local/cluster runtimes.

## Container Image

Build the ingestion job image from the repository root:

```bash
make ingestion-image
```

Or build directly:

```bash
docker build -f ingestion/Dockerfile -t eve-market-ingestion:local ingestion
```

Smoke check the entrypoint:

```bash
make ingestion-image-smoke
```

The image entrypoint is `eve-market-ingest`, so pass normal CLI arguments after the
image name:

```bash
docker run --rm eve-market-ingestion:local everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --sync-raw \
  --dev-mode
```

For Airflow DockerOperator local runs, build `eve-market-ingestion:local` before running
the DAG. The `Ingestion Image` GitHub Actions workflow builds the image on
`ubuntu-latest` and publishes trusted `master` builds to
`ghcr.io/<owner>/eve-market-ingestion`. Later KubernetesPodOperator runs should use an
immutable `sha-*` tag and mount shared storage at `/opt/eve-market/data`.

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --sync-raw \
  --dev-mode
```

By default, standalone CLI output uses DuckLake with a local SQLite catalog and local
DuckLake storage under `ingestion/.local/ducklake/everef_market_history`.

For Airflow or Kubernetes, mount the shared NFS PVC into the worker/pod and use the
mounted storage target. Mounted/shared DuckLake storage requires a non-local durable
catalog such as PostgreSQL. The local SQLite catalog default is only for local smoke
tests, and mounted DuckLake storage with a SQLite catalog is rejected.

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted \
  --ducklake-catalog postgresql://user:password@postgres.example/eve_market_ducklake
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
DuckLake attach name and catalog URL for scheduled workloads. Use
`EVE_MARKET_DUCKLAKE_CATALOG` or `--ducklake-catalog` for the PostgreSQL catalog URL
when `--storage-target mounted` or a mounted `EVE_MARKET_DUCKLAKE_STORAGE` path is used.

DuckLake destination configuration is resolved by the ingestion publisher layer rather
than by the source reader: the publisher applies the catalog and storage precedence,
creates local smoke-test paths when appropriate, and enforces the mounted-storage
catalog guardrail.

Validate the locked ingestion environment and tests from the ingestion project root:

```bash
uv run --locked pytest
```

## Raw Source-File Cache

Raw source-file acquisition is separate from dlt loading. It downloads Everef CSV
archives into a local or mounted raw cache, records checksums and source headers in a
SQLite or PostgreSQL ledger, and lets dlt read the cached file paths later.

Everef raw acquisition is intentionally thin: it adapts Everef probe metadata into a
generic `RawFileSpec`, then delegates cache-hit detection, download, checksum, ledger,
failure recording, and pruning behavior to `publish_raw_file`. This keeps source-specific
URL/probe logic separate from reusable raw-file cache mechanics.

Sync raw Everef market history files locally:

```bash
uv --project ingestion run eve-market-ingest raw-files sync-everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

Local raw cache defaults to `ingestion/.local/raw`. The ledger defaults to local
SQLite at `ingestion/.local/raw/raw_files.sqlite`.

For Airflow or Kubernetes, use the mounted target so raw files live under the shared
data root:

```bash
uv --project ingestion run eve-market-ingest raw-files sync-everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted \
  --data-root /mnt/eve-market/data \
  --raw-ledger-url postgresql://user:password@postgres.example/eve_market_raw_files
```

The mounted raw cache target resolves to `/opt/eve-market/data/raw` unless `--data-root`
or `EVE_MARKET_DATA_ROOT` changes the mounted root. Override the raw cache directly with
`--raw-root` or `EVE_MARKET_RAW_FILES_ROOT`. Mounted raw cache targets require an
explicit durable ledger URL through `--raw-ledger-url` or
`EVE_MARKET_RAW_FILES_LEDGER_URL`; they do not default to SQLite on shared storage.

Use SQLite for direct local ingestion runs. Use PostgreSQL for Docker Compose and later
k3s/Airflow deployments, while still treating raw-file acquisition as single-writer for
the relevant publication scope.

Load dlt from raw cache after sync:

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

When using the mounted cache, use the same storage target for both sync and load and
provide durable DuckLake catalog and raw-file ledger URLs through arguments or env vars:

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --storage-target mounted \
  --ducklake-catalog postgresql://user:password@postgres.example/eve_market_ducklake \
  --raw-ledger-url postgresql://user:password@postgres.example/eve_market_raw_files
```

Or do both in one local command:

```bash
uv --project ingestion run eve-market-ingest everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --sync-raw
```

`--sync-raw` downloads changed files first, then loads dlt from raw cache. Without it,
default CLI behavior expects cache entries to exist already and raises if they are
missing. Raw cache is source acquisition ledger, not dataset publication manifest.
Published analytical state remains DuckLake-backed.

Everef raw sync now uses `totals.json` as partition-level change detector by default.
Add `--check-headers` to also use `content-length`, `last-modified`, and `ETag` when
probing file changes. When `totals.json` row count stays the same but a re-downloaded
file hash changes, ingestion logs a warning for a same-count content change. If no
usable validators are available, the file is downloaded again rather than treated as
fresh.

The same command can be run through the module entrypoint:

```bash
uv --project ingestion run python -m ingest.cli everef-market-history \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

Before loading each chunk, the source validates the expected market history contract:
required columns, non-null keys, row `date` matching the source market date, numeric
values, non-negative numeric fields, and `highest >= lowest`.

The reader also enforces file-level uniqueness for `(region_id, type_id)` after the
market-day check, which is equivalent to the full `(date, region_id, type_id)` primary
key for one Everef daily file. Dataset-level replacement and idempotency are handled by
the publication contract and DuckLake merge/delete-insert behavior.

## Test Guidance

Prefer testing client helpers, contracts, and source generator behavior at their public
module boundaries. Avoid reaching into dlt private internals.

For raw-file behavior, keep tests split by boundary:

- `test_raw_files_publisher.py` covers generic `RawFileSpec` and `publish_raw_file`
  cache/download/prune behavior.
- `test_raw_files_repository.py` covers ledger persistence and backend SQL behavior.
- `test_raw_files_everef.py` covers Everef adapter/spec/list-cache behavior.
- `test_raw_files_config.py`, `test_raw_files_downloader.py`, and
  `test_raw_files_models.py` cover smaller supporting modules.

When a test consumes a dlt resource or transformer generator, collect a bounded number
of yielded values with `itertools.islice` or an equivalent helper. Do not materialize a
full date range or a full CSV stream unless the fixture is intentionally tiny.

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
- `--chunksize`: pandas CSV chunk size; omitted uses the source default `20000`.
- `--base-url`: override the Everef market history base URL for testing.
- `--input-source`: CSV read source, `url` or `raw-cache`, defaults to `url`.
- `--sync-raw`: download raw source files first, then load from `raw-cache`.
- `--raw-root`: raw source-file cache root override.
- `--raw-ledger-url`: raw source-file ledger URL override.

DuckLake storage URL precedence is explicit `--ducklake-storage`, then
`EVE_MARKET_DUCKLAKE_STORAGE`, then the selected `--storage-target` default. For
`mounted`, the default root is resolved from `--data-root`, then
`EVE_MARKET_DATA_ROOT`, then `/opt/eve-market/data`; for `local`, the SQLite catalog
and local DuckLake storage stay under
`ingestion/.local/ducklake/everef_market_history`. The mounted storage path is
`/opt/eve-market/data/ducklake/everef/market_history`.

Use a local SQLite DuckLake catalog only for local development and smoke tests. Use a
PostgreSQL DuckLake catalog for production-style Airflow or Kubernetes deployments, with
DuckLake data files on mounted shared storage. Mounted DuckLake storage selected by
`--storage-target mounted` or by an explicit/env mounted storage path is rejected when
the resolved catalog is SQLite. Do not place a shared writable `.duckdb` file on RWX/NFS.

DuckLake uses the DuckDB engine internally. If DuckDB is used for local experiments,
keep any writable `.duckdb` database on local or pod-scratch storage and never place a
shared writable `.duckdb` file on RWX/NFS.
