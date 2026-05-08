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
  --bucket-url file:///tmp/eve-market/dlt-staging/everef/market_history \
  --dev-mode
```

For Airflow or Kubernetes, mount the shared NFS PVC into the worker/pod and pass the
mounted path as a filesystem URL:

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
- `--bucket-url`: filesystem destination URL, or `EVE_MARKET_INGESTION_BUCKET_URL`.
- `--loader-file-format`: dlt loader file format, defaults to `parquet`.
- `--chunksize`: pandas CSV chunk size, defaults to `20000`.
- `--base-url`: override the Everef market history base URL for testing.

The filesystem destination requires an explicit bucket URL so Airflow and Kubernetes
jobs fail fast when the NFS mount path is not configured. The current `dlt` output is a
Parquet staging area; canonical dataset publication should validate and promote those
files into the shared storage contract with manifests. The market history table uses
`replace` writes so rerunning a scoped load does not imply unsupported filesystem
upserts.

DuckDB is not an ingestion dependency; if used for local experiments, keep the database
on local or pod-scratch storage and never place a shared writable `.duckdb` file on
RWX/NFS.
