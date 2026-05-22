# eve-market-analytics

Portfolio project for end-to-end economic analytics on virtual market datasets.

This repository is the analytics-first workspace: ingestion pipelines, dataset
contracts, transformations, orchestration, experiments, and architecture docs
for publishing and analyzing market data.

Readers looking for reusable homelab runtime, cluster bootstrap, shared storage
wiring, and production-style platform operations should use the companion
repository `homelab-data-platform`. This repo stays focused on workload
contracts, pipeline behavior, and local analytics development.

The canonical cross-repo workload-to-platform runtime contract lives in
`docs/runtime_contract.md`.

## Repo Map

- `ingestion/`: source clients, dlt pipelines, and dataset publication logic
- `datasets/`: contracts, schemas, reference data, and manifests
- `transform/`: dbt models, tests, and feature-building SQL
- `orchestration/`: Airflow DAGs and scheduling logic
- `experiments/`: validation work, model experiments, and evidence
- `docs/`: architecture, storage, lifecycle, and ADRs
- `infra/`: local analytics demo harness

> Note
> Some infrastructure and operational hardening is intentionally deferred until the
> main project build is complete. This includes current PostgreSQL follow-up work
> and similar finer details across other components, such as security,
> backup/recovery, and related production-polish concerns.

## Local Airflow + dlt Runtime

This is the local development and reviewer demo harness for the analytics repo.

Local Compose stack provides fast ingestion iteration and portfolio demo access without
requiring Proxmox, k3s, TrueNAS, or Helm. It runs Airflow with a local Postgres
metadata database, bind-mounted DAGs and project code, and local DuckLake data-file
storage under `.local/data`.

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
make local-airflow-down
make local-airflow-reset
make local-pipeline-smoke
```

Expected development loop:

1. edit ingestion and dlt code
2. run locally
3. validate through local Airflow
4. commit
5. validate in CI and publish GHCR image tags from trusted `master` builds
6. deploy through `homelab-data-platform`

See `infra/local/README.md` for local runtime details and
`docs/runtime_contract.md` for the workload-to-platform deployment contract.
