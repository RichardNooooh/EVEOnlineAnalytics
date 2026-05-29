# Ingestion

Standalone Python project for source-specific extraction and publication.

## Docker Compose (Primary Dev Path)

Primary execution path is the `infra/local/compose.yml` stack. Ingestion runs
inside Airflow via `DockerOperator`. See `infra/local/README.md` for setup.

Backfill DAGs in `orchestration/dags/backfill_dags.py` pass CLI args to the
ingestion container image. All runtime state (dlt scratch, temp files) goes to
ephemeral `/scratch` inside the container. Durable data lands under repo
`.local/data/`, mounted at `/opt/eve-market/data` inside the container.

Production-style Kubernetes deployment lives in
[`homelab-data-platform`](https://github.com/RichardNooooh/HomeLabDataPlatform).
This repo only provides the local Docker Compose demo harness.

## Building the Image

```bash
docker build -f Dockerfile -t eve-market-ingestion:local .
```

Container entrypoint is `eve-ingest`, so pass normal CLI args after the
image name.

## Storage Layout

- **Raw files**: cached under `/opt/eve-market/data/raw_files/`, backed by
  repo `.local/data/raw_files/`.
- **DuckLake datasets**: published under
  `/opt/eve-market/data/datasets/ducklake/raw/`, backed by
  repo `.local/data/datasets/ducklake/raw/`.
- **Catalog**: PostgreSQL (local postgres service in compose stack) for mounted
  storage. Local SQLite catalog is for smoke tests only.

## Useful Flags

- `--start-date`, `--end-date`: inclusive date range for daily archives (required for
  market-history, market-orders, fuzzwork-orders).
- `--data-root`: mounted shared data root (default `/opt/eve-market/data`).
- `--raw-ledger-url`: raw-file acquisition ledger PostgreSQL URL.
- `--ducklake-catalog`: DuckLake catalog URL (PostgreSQL for mounted, SQLite for
  local smoke tests).
- `--ducklake-metadata-schema`: DuckLake metadata schema name (default `eve_market`).

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
- Container runtime uses ephemeral `/scratch` for dlt state and temp files.
- Durable state remains DuckLake data plus PostgreSQL-backed services.
