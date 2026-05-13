# AGENTS.md

Reference file for agents working in this repo. Read this first, then read the
nearest scoped `AGENTS.md` for the area you are touching.

## Project Contract

**Name:** `eve-market-analytics`

**Purpose:** End-to-end data engineering and MLOps portfolio project for virtual
economy analytics. Present this as an economic analytics platform, not a gaming
project.

Emphasize economic modeling, anomaly detection, publication contracts, and pipeline
engineering.

## Hard Architecture Rules

- DuckLake tables backed by Parquet files are the analytical system of record.
- TrueNAS NFS is shared RWX storage for DuckLake data files, manifests, contracts,
  artifacts, and logs.
- DuckLake catalog metadata is durable state. Use PostgreSQL for production-style
  deployments; local SQLite is only for smoke tests.
- DuckDB is local or transient analytical compute only.
- Never create or depend on a cluster-shared writable `.duckdb` file.
- Dataset publication is single-writer for the relevant publication scope.
- Writers publish through DuckLake commits or merge/delete semantics and maintain
  contracts/manifests where useful.
- DuckDB databases used by dbt or batch jobs must live on pod scratch such as
  `emptyDir` or node-local `ReadWriteOnce` volumes, never shared NFS.

Primary architecture references: `docs/architecture.md`, `docs/data_lifecycle.md`,
`docs/storage_layout.md`, ADR-016, and ADR-020.

## Scoped Guides

- Documentation and ADRs: `docs/AGENTS.md`
- Dataset contracts, schemas, reference data, manifests: `datasets/AGENTS.md`
- Ingestion sources, clients, pipelines, publishers: `ingestion/AGENTS.md`
- dbt transforms and SQL models: `transform/AGENTS.md`
- Airflow DAGs and orchestration: `orchestration/AGENTS.md`
- Infrastructure, Kubernetes, Helm, OpenTofu, Ansible: `infra/AGENTS.md`
- Experiments and validation evidence: `experiments/AGENTS.md`

## Tool Boundaries

Every tool has a distinct purpose. Do not add new tools without justification.

| Layer | Tool | Purpose |
|---|---|---|
| Extract + Publish | Python + dlt | Source-specific ingestion and dataset publication tasks orchestrated by Airflow |
| Storage | DuckLake over Parquet files | Durable raw and curated analytical tables, contracts, catalog metadata, and shared reader state |
| Compute | DuckDB | Local dev queries, dbt work DBs, and single-writer batch compute only |
| Transform | dbt | SQL transformations, tests, and documentation |
| Orchestration | Airflow | DAG-based scheduling for ingestion, transforms, training, predictions, and monitoring |
| Cloud-readiness | Snowflake + OpenTofu | Managed warehouse proof path; not steady-state runtime |
| BI | Tableau | Market analytics visualization |
| Experiment Tracking | MLflow | Training runs, parameters, metrics, model registry |
| Model Serving | BentoML | REST API serving trained models |
| Model Monitoring | Evidently | Data drift, prediction drift, retraining triggers |
| Infra Monitoring | VictoriaMetrics + Grafana | Pipeline health, durations, API errors, resource usage |

Explicit non-goals: Airbyte, Great Expectations, DVC, and PowerBI.

## Global Conventions

- Use `mise` to handle tooling.
- Python uses `ruff` and `uv`. Keep repo-wide Python tool configuration such as
  Ruff in the repo-root `pyproject.toml`. Keep package metadata, dependencies,
  scripts, pytest config, and locks in the scoped Python project that owns them,
  such as `ingestion/pyproject.toml` and `ingestion/uv.lock`, unless the repo is
  deliberately migrated to a root `uv` workspace.
- Do not directly modify `uv.lock` or `pyproject.toml` if a `uv` command can do it by itself.
  Example: Do not add a package directly to `pyproject.toml`; use `uv add {package}`.
- SQL uses lowercase keywords, CTEs over subqueries, one model per file, and prefixes
  such as `stg_`, `int_`, `mart_`, and `feat_`.
- OpenTofu uses standard HCL formatting with `tofu fmt`.
- Git uses conventional commits. Feature branches are off `master`; PRs are required.
- Commit titles and bodies use prefixes such as `docs:`, `cleanup:`, `feat:`,
  `refactor:`, or `fix:` followed by a capitalized action verb.
- Commit bodies should use one `{prefix}: {Verb}...` line per change and append
  `Co-Authored-By: GPT-5.5 (high) via OpenCode`.

## Common Task Routing

- Add a new data source: update ingestion, dataset contracts, data dictionary, and
  planned dbt staging sources.
- Add a new ML feature: update `transform/models/ml_features/` contracts and related
  dataset/documentation.
- Write a dbt test: prefer schema YAML or `transform/tests/` when the dbt project
  exists.
- Update storage architecture: start with `docs/architecture.md`,
  `docs/storage_layout.md`, and ADRs before implementation.
- Add monitoring dashboard: update Grafana provisioning and Kubernetes dashboard
  manifests if the dashboard is checked in.
- Diagnose errors: identify likely fixes, then validate with local evidence or online
  references when useful.
