# Runtime And Deployment Contract

## Purpose

This document is the canonical workload-to-platform runtime contract between
`eve-market-analytics` and `homelab-data-platform`.

`eve-market-analytics` defines workload behavior, required mounts, durable-state
boundaries, image expectations, and DAG/runtime inputs. `homelab-data-platform`
implements reusable Docker Compose, Kubernetes, storage, PostgreSQL,
observability, and deployment wiring that satisfies those requirements.

## Ownership Split

### Workload-owned in `eve-market-analytics`

- ingestion code, publishers, and source clients under `ingestion/`
- dataset contracts, schemas, manifests, and reference data under `datasets/`
- dbt models, tests, and docs under `transformation/`
- Airflow DAG source under `orchestration/dags/`
- Compose-run Evidence app under `bi/`
- local analytics harness under `infra/local/`
- workload architecture and storage contracts under `docs/`
- container image build inputs for workload images such as `ingestion/Dockerfile`

### Platform-owned in `homelab-data-platform`

- cluster bootstrap, node provisioning, and reusable infrastructure automation
- shared storage provisioning and mount wiring for workload runtimes
- production-style Airflow deployment/runtime implementation
- PostgreSQL service deployment, backup, and connection-secret delivery
- ingress, TLS, DNS, observability stack, and runtime hardening
- deployment manifests, Helm values, Compose files, and image rollout wiring

## Storage And State Contract

- DuckLake tables backed by Parquet files are the canonical analytical system of record.
- Production-style or mounted/shared DuckLake catalogs must use PostgreSQL.
- No runtime may depend on a cluster-shared writable `.duckdb` file.
- Publication is single-writer for the relevant dataset or partition scope.
- PostgreSQL advisory locks over stable DuckLake lock domains enforce single-writer
  publication semantics; semantic publication scopes remain ledger-facing names, and
  Airflow DAG-level `max_active_runs=1` is only an outer guard.
- DuckLake raw data-table and provenance-table mutations require a lock token covering
  the target physical table domain; semantic publication scope alone is not enough.
- Raw DuckLake schema and dataset-scoped provenance tables must be bootstrapped
  explicitly before first writer use in a new catalog/schema.
- Bootstrap jobs must acquire `ducklake:migration` plus affected raw/support lock domains
  before raw schema or table DDL.
- Maintenance jobs that mutate DuckLake metadata or table state must acquire
  `ducklake:maintenance` plus affected raw/support lock domains; `ducklake:maintenance`
  alone is not a global writer gate.

### Durable mounts

- shared DuckLake data-file root for published raw and curated datasets
- shared manifests/contracts/artifact roots when the runtime exposes them directly
- Airflow log root when logs are persisted outside container-local storage

### Scratch mounts

- job-local scratch for DuckDB work databases
- job-local scratch for containerized `dlt` runtime state
- temporary unpublished writer state

Scratch mounts must be ephemeral and separate from DuckLake durable storage.

## Environment Contract

### Local Docker Compose runs

These are the reviewer/development runtime flows under `infra/local/`.

- `eve-market-analytics` owns the Compose-facing workload inputs: DAG source,
  ingestion code, dbt project, contracts, and local image build context
- this repo's `.local/data` is the local durable DuckLake data-file stand-in
- this repo's `.local/logs` is the local Airflow log mount
- Airflow metadata DB and raw-file ledger DB run in local Postgres services
- local Evidence runs in Compose and reads curated DuckLake state over container-visible mounts
- `orchestration/dags` is bind-mounted DAG source from this repo
- task containers use explicit ephemeral scratch for `dlt` runtime state rather
  than repo-local host paths or host-driven ingestion execution
- local task image may use `eve-market-ingestion:local`
- when you want reviewer-stack local data for transform work, publish it through this
  Docker Compose path so data files land under `.local/data`
- local Compose-run Evidence may then read curated DuckLake publications from `.local/data`
  as a read-only BI consumer
- host dbt may attach directly to local Compose PostgreSQL-backed DuckLake catalogs
  as the supported host-side exception

### Kubernetes / production-style runs

These are platform-managed runtime deployments implemented in
`homelab-data-platform`.

- `eve-market-analytics` supplies workload images, DAG source contract, dataset
  contracts, and storage/runtime requirements
- `homelab-data-platform` supplies the Airflow runtime, mount wiring,
  PostgreSQL-backed services, secrets, scheduling, and rollout implementation
- published DuckLake data files live on shared durable RWX storage
- DuckLake catalog metadata uses PostgreSQL, not SQLite
- Airflow metadata uses PostgreSQL
- raw-file acquisition ledger uses PostgreSQL
- job scratch uses pod-local storage such as `emptyDir` or node-local
  `ReadWriteOnce` volumes
- production DAG execution should use immutable workload images, not Docker socket
  access or bind-mounted repo code

## Runtime Inputs By Concern

### DAG source

- canonical DAG source lives in `eve-market-analytics/orchestration/dags`
- local Compose may bind-mount that path directly
- Kubernetes / production-style runtime may package or sync DAGs, but deployed
  DAG code must come from this repo's reviewed source

### PostgreSQL

- Airflow metadata database is platform-owned runtime infrastructure
- DuckLake catalog PostgreSQL is platform-owned for mounted/shared and
  production-style deployments
- raw-file acquisition ledger PostgreSQL is platform-owned for Compose and
  Kubernetes-style multi-container runs

### Logs

- workload code may emit task/application logs
- persisted Airflow/runtime log storage and retention policy are platform-owned
- local Compose persists logs under `.local/logs`

### Durable mounts

- workload contract requires durable mounts for published DuckLake data files
- manifests, contracts, and artifacts may share the same durable storage root or
  an equivalent platform-managed layout
- exact host paths, PVC names, storage classes, and NFS exports are
  platform-implementation details

### Scratch mounts

- workload contract requires explicit scratch for DuckDB work DBs and
  containerized `dlt` state
- local Compose-run Evidence is not a scratch-state producer; it reads published curated
  DuckLake state through workload-defined dataset contracts
- exact mount names and sizes are platform-implementation details

## Image And Tag Contract

- workload images are built from `eve-market-analytics`
- local Compose may use `eve-market-ingestion:local` for developer iteration
- deployable ingestion images are published to
  `ghcr.io/<owner>/eve-market-ingestion:<immutable-tag>`
- Kubernetes / production-style Airflow tasks must reference immutable image tags
  published from trusted CI, not mutable local tags
- platform deployment config in `homelab-data-platform` must treat image
  repository and tag as workload inputs rather than duplicating build logic

## What The Platform Repo Should Reference

`homelab-data-platform` should reference this document when defining:

- Airflow deployment mounts and DAG delivery
- PostgreSQL instances or schemas for Airflow metadata, DuckLake catalog, and raw ledger
- durable RWX storage for DuckLake data files and persisted logs
- scratch mounts for writer pods and dbt/ingestion jobs
- workload image repository and immutable tag inputs

Related workload docs:

- `docs/architecture.md`
- `docs/data_lifecycle.md`
- `docs/storage_layout.md`
- `infra/local/README.md`
