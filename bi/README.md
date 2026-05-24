# Evidence App

Host-run Evidence app for read-only BI over published curated DuckLake state.

## Purpose

- consume published curated DuckLake tables only
- do not read dbt scratch DuckDB work databases
- do not write analytical state

Current curated pages read:

- `curated.curated_daily_prices`
- `curated.curated_trade_volume`

## Prerequisites

- local reviewer stack running from `infra/local/`
- curated publish completed into repo-root `.local/data`
- local Postgres DuckLake catalog reachable on `127.0.0.1:5432`
- Node and npm from repo `mise.toml`

## Local Setup

```bash
cp .env.example .env
npm install
npm run sources
npm run dev
```

Open local app at `http://localhost:3000` unless Evidence chooses another port.

## Build

```bash
npm run build
npm run preview
```

## Data Source Notes

- source config lives in `sources/curated_ducklake/`
- Evidence uses DuckDB in-process and attaches DuckLake with `read_only`
- local source queries reuse `CURATED_DUCKLAKE_*` naming from `transformation/`
- if curated publication is missing from local DuckLake catalog, `npm run sources` fails by design
