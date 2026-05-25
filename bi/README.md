# Evidence App

Compose-run Evidence app for read-only BI over published curated DuckLake state.

## Purpose

- consume published curated DuckLake tables only
- do not read dbt scratch DuckDB work databases
- do not write analytical state

Current curated pages read:

- `curated.curated_daily_prices`
- `curated.curated_trade_volume`

## Prerequisites

- local reviewer stack running from `infra/local/`
- host `dbt build` completed so curated DuckLake tables exist under repo-root `.local/data`
- local Compose Postgres DuckLake catalog reachable as `postgres:5432` inside Compose

## Local Setup

```bash
make local-airflow-up
make local-bi-up
make local-bi-smoke
```

Open local app at `http://localhost:3000` in host browser. Compose serves Evidence
from container; browser entrypoint stays local.

Stop local BI service:

```bash
make local-bi-down
```

## Data Source Notes

- source config lives in `sources/curated_ducklake/`
- Evidence uses DuckDB in-process and attaches DuckLake with `read_only`
- local source queries reuse `CURATED_DUCKLAKE_*` naming from `transformation/` through
  Evidence `EVIDENCE_VAR__*` environment mapping in Compose
- Compose service mounts repo-root `.local/data` read-only at `/data`
- if curated publication is missing from local DuckLake catalog, `make local-bi-smoke` and `make local-bi-up` fail by design
