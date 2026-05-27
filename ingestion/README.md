# Ingestion

Python ingestion package for raw source acquisition and DuckLake publication.

This code owns workload behavior: fetch raw files, keep source-file ledger metadata,
and publish validated Arrow data into DuckLake-backed raw tables. Durable metadata uses
PostgreSQL. DuckDB connections are local/transient compute only.

## Commands

Run tests from this directory:

```bash
uv run pytest
```
