# AGENTS.md

Reference file for LLM agents working on this project. Read this before writing any
code or answering architectural questions.

## Project Overview

**Name:** eve-market-analytics
**Purpose:** End-to-end data engineering + MLOps resume project. Ingests EVE Online
market data, publishes analytical datasets, transforms them for ML and BI use cases,
serves predictions via API, and monitors everything.
**Framing:** Present as a virtual economy analytics platform, not a gaming project.
Emphasize economic modeling, anomaly detection, publication contracts, and pipeline
engineering.

## Canonical Architecture Contract

- **System of record:** published Parquet datasets on shared storage.
- **Shared storage:** TrueNAS NFS exported into k3s as RWX storage for Parquet datasets,
  manifests, artifacts, and logs.
- **Compute:** DuckDB is local or transient analytical compute only.
- **Forbidden pattern:** there is no cluster-shared writable `.duckdb` file.
- **Writer model:** dataset publication is single-writer for the relevant publication
  scope.
- **Publication model:** writers use temp-write then promote semantics and publish
  manifests/contracts.
- **Scratch storage:** any DuckDB database used by dbt or batch jobs must live on pod
  scratch such as `emptyDir` or node-local `ReadWriteOnce` volumes, never RWX shared
  NFS.

See `docs/architecture.md`, `docs/data_lifecycle.md`, `docs/storage_layout.md`, and
ADR-016 for the current contract.

## Data Sources

### everef.net (Historical Backfill)

- **Market History:** `data.everef.net/market-history/` - Daily CSV archives. Same
  schema as ESI `/markets/{region_id}/history/`. Contains data beyond the ESI 1-year
  lookback.
- **Market Order Snapshots:** `data.everef.net/market-orders/` - Full order book
  snapshots, twice per hour. Compressed CSV with headers.
- Archives may be updated in place as new data is discovered. Planned ingestion should
  use source metadata such as `totals.json` to detect changes and republish affected
  partitions.

### EVE ESI API (Live Ingestion)

- **Market History:** `GET /markets/{region_id}/history/?type_id={type_id}`
- **Market Orders:** `GET /markets/{region_id}/orders/`
- **Rate limit:** 300 requests/minute globally. Respect `Expires` headers. Too many
  errors can trigger a temporary ban.
- **No auth required** for market endpoints.
- **Critical data quirk:** the `average` field in market history is actually the
  **median**, not the mean. Document this everywhere a schema contract is written.

### ESI Market History Fields

```json
{
  "average": 5.25,
  "date": "2015-05-01",
  "highest": 5.27,
  "lowest": 5.11,
  "order_count": 2267,
  "volume": 16276782035
}
```

## Key Reference IDs

- **The Forge (primary region):** `10000002`
- **Jita:** `30000142`
- Type IDs come from the Static Data Export. Reference datasets should map `type_id`
  to item names.

## Tech Stack

Every tool has a distinct, non-overlapping purpose. Do not add tools without
justification.

| Layer | Tool | Purpose |
|---|---|---|
| Extract + Publish | **Python + dlt** | Source-specific ingestion and dataset publication tasks orchestrated by Airflow |
| Storage | **Parquet on shared NFS** | Durable raw and curated datasets, manifests, contracts, and shared reader state |
| Compute | **DuckDB** (local/transient only) | Local dev queries, dbt work DBs, and single-writer batch compute |
| Transform | **dbt** (Parquet sources, local DuckDB work DB, Snowflake proof target) | SQL transformations, tests, and documentation |
| Orchestration | **Airflow** | DAG-based scheduling for ingestion, transforms, training, predictions, and monitoring |
| Cloud-readiness | **Snowflake** (OpenTofu/Terraform) | IaC code proves a managed warehouse path; not kept live |
| BI / Dashboards | **Tableau** | Market analytics visualization for end users |
| Experiment Tracking | **MLflow** | Training runs, hyperparameters, metrics, model registry |
| Model Serving | **BentoML** | REST API serving trained models |
| Model Monitoring | **Evidently** | Data drift, prediction drift, retraining triggers |
| Infra Monitoring | **VictoriaMetrics + Grafana** | Pipeline health, job durations, API error rates, resource usage |

### Tools Explicitly Not Used

- **Airbyte:** Heavy self-hosted footprint and the wrong abstraction for explicit
  single-writer dataset publication.
- **Great Expectations:** Overlaps with dbt tests for this scope.
- **DVC:** Published Parquet datasets plus manifests cover persisted analytical data;
  MLflow handles model artifacts.
- **PowerBI:** Redundant with Tableau.

## ML Models

### Primary: Market Anomaly Classification

- **Objective:** classify each `(item, region, day)` observation as normal or anomalous.
- **Sub-classes:** price spike, volume spike, suspected manipulation, supply shock.
- **Metrics:** Precision, Recall, F1, AUC-ROC.
- **Labeling strategy:** semi-supervised. Use statistical thresholds (`>3 sigma` from a
  trailing mean) to generate pseudo-labels, then train a supervised classifier.
- **Why this model:** directly analogous to fraud detection and market surveillance.

### Secondary: Price Direction Classification

- **Objective:** predict whether next-day median price goes up, down, or flat.
- **Metrics:** accuracy and per-class F1.
- **Baseline:** naive same-as-today predictor.

### Feature Engineering

Planned dbt `ml_features/` contracts should produce:

- rolling 7d, 14d, and 30d price and volume statistics
- price volatility: `(highest - lowest) / average`
- volume z-score relative to trailing 30d windows
- cross-region price divergence
- order count / volume ratio as a market-depth proxy
- temporal features such as day-of-week and days-since-last-patch

## Planned Directory Structure

This structure is the target design contract. Parts of it are not implemented yet.

```text
eve-market-analytics/
├── README.md
├── AGENTS.md
├── docs/
│   ├── architecture.md
│   ├── data_lifecycle.md
│   ├── storage_layout.md
│   ├── data_dictionary.md
│   ├── model_card.md
│   └── adr/
│
├── ingestion/
│   ├── README.md
│   ├── dlt.yml                         # optional later
│   ├── eve_market_ingestion/
│   │   ├── sources/
│   │   ├── clients/
│   │   ├── pipelines/
│   │   ├── publishers/
│   │   ├── contracts/
│   │   └── cli.py
│   └── tests/
│
├── datasets/
│   ├── README.md
│   ├── contracts/
│   ├── schemas/
│   ├── reference/
│   └── examples/
│       └── manifests/
│
├── transform/
│   ├── README.md
│   ├── dbt_project.yml
│   ├── profiles.example.yml
│   ├── models/
│   │   ├── staging/
│   │   │   ├── everef/
│   │   │   └── esi/
│   │   ├── intermediate/
│   │   ├── marts/
│   │   └── ml_features/
│   ├── macros/
│   ├── tests/
│   ├── seeds/
│   └── analyses/
│
├── orchestration/
│   ├── README.md
│   ├── dags/
│   │   ├── ingestion/
│   │   ├── transform/
│   │   └── ml/
│   ├── include/
│   └── plugins/
│
├── ml/
│   ├── training/
│   ├── evaluation/
│   ├── serving/
│   ├── monitoring/
│   └── README.md
│
├── dashboards/
├── monitoring/
├── infra/
├── pyproject.toml
└── .github/
```

## Deployment Strategy

### Platform

- Kubernetes-managed application workloads run on a 3-node k3s cluster deployed across
  a Proxmox homelab.
- All 3 nodes are k3s server nodes with workload scheduling enabled.
- Shared storage is provided by TrueNAS NFS and exposed to the cluster through RWX
  PersistentVolumes.
- Shared NFS stores published Parquet datasets, manifests, MLflow artifacts, and
  Airflow logs.
- Airflow metadata uses an external PostgreSQL server on its own Proxmox VM rather than
  another service inside `k3s`. That same server may later host MLflow in separate
  databases and credentials.
- DuckDB work databases are local or transient scratch only and must not be shared
  across pods through RWX storage.

### IaC Layers

1. **OpenTofu (`infra/terraform/proxmox/`)** provisions the 3 Debian 13 VMs.
2. **Ansible (`infra/ansible/`)** bootstraps k3s, installs NFS client utilities, and
   verifies shared storage connectivity.
3. **kubectl + Helm (`infra/k8s/` and `infra/helm/`)** applies namespaces, shared NFS
   storage contracts, and Kubernetes-managed service deployments. Helm values follow
   `infra/helm/<service>.yml` naming such as `airflow.yml` and `mlflow.yml`.

### Snowflake Cloud-Readiness

- Snowflake IaC is a planned cloud-readiness path and is not checked into this repo
  yet.
- The steady-state architecture remains self-hosted Parquet datasets plus local or
  transient compute.

### RAM Budget

| Component | Estimated Memory | Notes |
|---|---|---|
| k3s overhead (x3) | ~1.5 GB | ~512 MB per server node |
| Airflow | 2-3 GB | Webserver + scheduler + worker |
| MLflow | 0.5-1 GB | Tracking server only |
| Grafana | 0.5 GB | Lightweight |
| VictoriaMetrics | 0.5-1 GB | Single-node mode |
| DuckDB work DBs | 1-2 GB | Depends on active batch/query workload |
| BentoML | 0.5-1 GB | Model serving |
| Evidently | 0.5 GB | Periodic workload |
| **Headroom** | **~26-32 GB** | Burst capacity and OS cache |

Resource requests and limits must be set in every Helm values file, including
`infra/helm/airflow.yml` and `infra/helm/mlflow.yml` when those service values are
checked in.

## Coding Conventions

- **Python:** format with `ruff`, use `uv`, and prefer a repo-root `pyproject.toml`
  for Python tool configuration when Python packages are added. Today, tool bootstrap
  is managed through `mise.toml`.
- **SQL (dbt):** lowercase keywords, CTEs over subqueries, one model per file,
  descriptive prefixes such as `stg_`, `int_`, `mart_`, and `feat_`.
- **OpenTofu:** standard HCL formatting with `tofu fmt`.
- **Git:** conventional commits. Feature branches off `master`. PRs required.
- **Mise:** use `mise` to handle all tooling.

## Common Agent Tasks

- **Add a new data source** -> update the ingestion contract, dataset contract,
  `docs/data_dictionary.md`, and planned dbt staging source definitions.
- **Add a new ML feature** -> update `transform/models/ml_features/` contracts and the
  corresponding dataset/documentation.
- **Write a dbt test** -> prefer schema YAML or `transform/tests/` when the dbt project
  exists.
- **Update storage architecture** -> start with `docs/architecture.md`,
  `docs/storage_layout.md`, and ADRs before touching implementation.
- **Set up a monitoring dashboard** -> update Grafana provisioning in
   `infra/helm/grafana.yml` and add Kubernetes dashboard ConfigMaps/manifests under
   `infra/k8s/` if the dashboard should be checked in.
- **Update Airflow or MLflow deployment values** -> use `infra/helm/airflow.yml` and
  `infra/helm/mlflow.yml` as the expected Helm values filenames for those services.
- **Write OpenTofu for Snowflake** -> create a new `infra/terraform/snowflake/`
  module only when the user explicitly asks for cloud-readiness IaC beyond the current
  Proxmox stack.
- **Update documentation** -> prefer `docs/` first, then `README.md` if needed.
- **Write commit** -> use `docs: `, `cleanup: `, `feat: `, `refactor: `, or `fix: `
  prefixes, followed by capitalized action verb like `feat: Add...` in both title and
  body. Body should have a sequence of `{prefix}: {Verb}...` for each change. Each one
  should be on a new line (ensure no raw `\n` characters). Append co-authorship as
  `Co-Authored-By: {Model} ({effort level}) via OpenCode`; e.g.
  `Co-Authored-By: GPT-5.4 (high) via OpenCode`.
- **Diagnosing Errors** -> Attempt to identify fixes and solutions, then validate by
  searching online. Solutions are rarely unique.
