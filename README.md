# eve-market-analytics

Portfolio project for end-to-end economic analytics on virtual market datasets.

This repository is the analytics-first workspace: ingestion pipelines, dataset
contracts, transformations, orchestration, BI, experiments, and architecture
docs for publishing and analyzing market data.

Readers looking for reusable homelab runtime, cluster bootstrap, shared storage
wiring, and production-style platform operations should use the companion
repository `homelab-data-platform`. This repo stays focused on workload
contracts, pipeline behavior, and local analytics development.

The canonical cross-repo workload-to-platform runtime contract lives in
`docs/runtime_contract.md`.

## Repo Map

- `ingestion/`: source clients, dlt pipelines, and dataset publication logic
- `datasets/`: contracts, schemas, reference data, and manifests
- `transformation/`: dbt models, tests, and feature-building SQL
- `orchestration/`: Airflow DAGs and scheduling logic
- `bi/`: Compose-run Evidence BI app over curated DuckLake publications
- `experiments/`: validation work, model experiments, and evidence
- `docs/`: architecture, storage, lifecycle, and ADRs
- `infra/`: local Airflow and published-data demo harness

> Note
> Some infrastructure and operational hardening is intentionally deferred until the
> main project build is complete. This includes current PostgreSQL follow-up work
> and similar finer details across other components, such as security,
> backup/recovery, and related production-polish concerns.

## Local Compose Runtime

This is local development and reviewer demo harness for published-data side of analytics repo.

Local Compose stack provides fast ingestion iteration and portfolio demo access without
requiring Proxmox, k3s, TrueNAS, or Helm. It runs Airflow with a local Postgres
metadata database, stock `apache/airflow` containers, bind-mounted DAGs and project
code, and local DuckLake data-file storage under `.local/data`.

Compose-run BI app lives under `bi/`. It reads published curated DuckLake state from
`.local/data` as read-only consumer after host `dbt build` materializes final curated
tables.

Host dbt remains supported from `transformation/` as local exception. It attaches to
local Compose PostgreSQL-backed DuckLake catalogs while keeping its scratch DuckDB
work database on host-local storage.

This runtime is a development harness, not production. It does not replace the
analytics architecture documented in `docs/architecture.md`. Production-style
platform deployment belongs in `homelab-data-platform`.

Local SQLite DuckLake catalogs are for local smoke tests only. Mounted/shared DuckLake
storage requires a non-local durable catalog such as PostgreSQL; ingestion rejects
mounted DuckLake storage with a SQLite catalog.

Production mapping:

- `.local/data` approximates TrueNAS NFS DuckLake data-file storage
- local Postgres approximates the Airflow metadata database and raw-file
  acquisition ledger database
- bind-mounted DAGs and code approximate the deployed Airflow image or sync mechanism

Basic commands:

```bash
make local-airflow-up
make local-bi-up
make local-airflow-down
make local-airflow-reset
make local-pipeline-smoke
```

Expected development loop:

1. edit ingestion and dlt code
2. run raw publication through local Airflow
3. run host dbt against local Compose PostgreSQL
4. validate local BI through Compose Evidence
5. commit
6. validate in CI and publish GHCR image tags from trusted `master` builds
7. deploy through `homelab-data-platform`

See `infra/local/README.md` for local runtime details, `bi/README.md` for local BI
app usage, `transformation/README.md` for host dbt against Compose PostgreSQL, and
`docs/runtime_contract.md` for workload-to-platform deployment contract.
