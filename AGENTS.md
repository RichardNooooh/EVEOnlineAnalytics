# AGENTS.md

Reference file for LLM agents working on this project. Read this before writing any code or answering architectural questions.

## Project Overview

**Name:** eve-market-analytics
**Purpose:** End-to-end data engineering + MLOps resume project. Ingests EVE Online market data, transforms it, trains anomaly detection and price direction models, serves predictions via API, and monitors everything.
**Framing:** Present as a "virtual economy analytics platform," not a gaming project. Emphasize economic modeling, anomaly detection, and pipeline engineering.

## Data Sources

### everef.net (Historical Backfill)
- **Market History:** `data.everef.net/market-history/` — Daily CSV archives. Same schema as ESI `/markets/{region_id}/history/`. Contains data beyond the ESI's 1-year lookback.
- **Market Order Snapshots:** `data.everef.net/market-orders/` — Full order book snapshots, twice per hour (at :15 and :45). Compressed CSV with headers.
- Archives may be updated in-place as new data is discovered. Use `totals.json` to detect changes.

### EVE ESI API (Live Ingestion)
- **Market History:** `GET /markets/{region_id}/history/?type_id={type_id}` — Returns daily OHLCV-like data per item per region.
- **Market Orders:** `GET /markets/{region_id}/orders/` — Returns current buy/sell orders. Paginated.
- **Rate limit:** 300 requests/minute globally. Respect `Expires` headers. Error rate limiting applies — too many errors triggers a temporary ban.
- **No auth required** for market endpoints (public data).
- **Critical data quirk:** The `average` field in market history is actually the **median**, not the mean. This is a confirmed bug (esi-issues #451). Document this in data dictionaries and transformations.

### ESI Market History Fields
```json
{
  "average": 5.25,    // actually MEDIAN, not mean
  "date": "2015-05-01",
  "highest": 5.27,
  "lowest": 5.11,
  "order_count": 2267,
  "volume": 16276782035
}
```

### Key Reference IDs
- **The Forge (primary region):** region_id `10000002` (contains Jita, the main trade hub)
- **Jita:** system_id `30000142`
- Type IDs come from the Static Data Export (SDE). Seed files should map type_id → item name.

## Tech Stack

Every tool has a distinct, non-overlapping purpose. Do not add tools without justification.

| Layer | Tool | Purpose |
|---|---|---|
| Extract + Load | **Airbyte** (self-hosted) | Custom connector for ESI API; managed connector patterns |
| Transform | **dbt** (dbt-duckdb / dbt-snowflake) | SQL transformations, data quality tests, documentation |
| Orchestration | **Airflow** | DAG-based scheduling: ingestion, transforms, training, predictions, monitoring |
| Warehouse | **DuckDB** (local) | Analytical queries, zero-cost local dev |
| Cloud-readiness | **Snowflake** (OpenTofu/Terraform) | IaC code proves cloud deployment path; not kept live (trial expires in 30 days) |
| BI / Dashboards | **Tableau** (Tableau Public) | Market analytics visualization for end users |
| Experiment Tracking | **MLflow** | Training runs, hyperparameters, metrics, model registry |
| Model Serving | **BentoML** | REST API serving trained models |
| Model Monitoring | **Evidently** | Data drift, prediction drift, retraining triggers |
| Infra Monitoring | **VictoriaMetrics + Grafana** | Pipeline health, job durations, API error rates, resource usage |

### Tools Explicitly NOT Used (and Why)
- **Fivetran:** SaaS dependency, no native ESI connector, would still require custom Python extraction. Airbyte self-hosted is open-source and more resume-appropriate.
- **Great Expectations:** Overlap with dbt tests. dbt tests cover schema, business logic, and freshness validation sufficiently for this project's scope. Mention GX in docs as a production-scale addition.
- **DVC:** The warehouse serves as the versioned data store. Training datasets are reconstructed via dbt queries, not materialized files. MLflow artifact store handles model versioning.
- **PowerBI:** Redundant with Tableau. One BI tool is sufficient.

## ML Models

### Primary: Market Anomaly Classification
- **Objective:** Classify each (item, region, day) observation as normal or anomalous.
- **Sub-classes:** price spike, volume spike, suspected manipulation, supply shock.
- **Metrics:** Precision, Recall, F1, AUC-ROC.
- **Labeling strategy:** Semi-supervised. Use statistical thresholds (>3σ from trailing mean) to generate pseudo-labels, then train a supervised classifier. Optionally bootstrap with Isolation Forest.
- **Why this model:** Directly analogous to fraud detection / market surveillance. Clear evaluation metrics. Avoids the trap of "my model predicts prices" (which invites skepticism).

### Secondary: Price Direction Classification
- **Objective:** Predict whether next-day median price goes up, down, or flat (3-class).
- **Metrics:** Accuracy, per-class F1.
- **Baseline:** Naive "same as today" predictor. Goal is to beat this baseline.

### Feature Engineering (computed in dbt `ml_features/`)
- Rolling statistics: 7d, 14d, 30d averages and standard deviations for price and volume.
- Price volatility: `(highest - lowest) / average` as daily range percentage.
- Volume z-score: relative to trailing 30d window.
- Cross-region price divergence: same item across regions (e.g., The Forge vs. Domain).
- Order count / volume ratio: proxy for market depth.
- Temporal features: day-of-week, days-since-last-patch (EVE patches affect markets).

## Directory Structure

```
eve-market-analytics/
├── README.md                              # Project overview, architecture diagram, setup instructions
├── AGENTS.md                              # This file
├── docs/
│   ├── architecture.md                    # System design, data flow diagrams
│   ├── data_dictionary.md                 # Schema definitions, field descriptions, known quirks
│   └── model_card.md                      # Model objectives, metrics, limitations, ethical considerations
│
├── ingestion/                             # EL layer
│   ├── everef_historical/                 # Backfill scripts for everef.net bulk data
│   │   ├── download_market_history.py
│   │   ├── download_market_orders.py
│   │   └── load_to_duckdb.py
│   ├── esi_live/                          # Live ESI API ingestion (used by Airbyte custom connector)
│   │   ├── market_history_scraper.py
│   │   ├── market_orders_scraper.py
│   │   └── rate_limiter.py
│   └── README.md
│
├── warehouse/                             # DuckDB schema management
│   ├── seeds/                             # Static reference data (SDE type IDs, region IDs, item names)
│   ├── migrations/                        # Schema evolution scripts
│   └── README.md
│
├── transform/                             # dbt project
│   ├── dbt_project.yml
│   ├── profiles.yml                       # Targets: dev (DuckDB), prod (Snowflake)
│   ├── models/
│   │   ├── staging/                       # 1:1 source mirrors: stg_market_history, stg_market_orders
│   │   ├── intermediate/                  # Regional aggregations, spread calculations, joins
│   │   ├── marts/                         # Final analytics tables for dashboards
│   │   │   ├── mart_daily_prices.sql
│   │   │   ├── mart_trade_volume.sql
│   │   │   ├── mart_regional_spreads.sql
│   │   │   └── mart_anomaly_summary.sql
│   │   └── ml_features/                   # Feature tables consumed by training scripts
│   │       └── feat_item_daily.sql
│   ├── tests/                             # Custom data quality tests (beyond schema tests in YAML)
│   ├── macros/
│   └── README.md
│
├── ml/                                    # Machine learning
│   ├── training/
│   │   ├── train_anomaly_detector.py
│   │   ├── train_price_classifier.py
│   │   └── feature_engineering.py         # Python-side feature transforms not handled by dbt
│   ├── evaluation/
│   │   ├── evaluate_model.py
│   │   └── backtesting.py
│   ├── serving/                           # BentoML
│   │   ├── service.py
│   │   └── bentofile.yaml
│   ├── monitoring/                        # Evidently
│   │   ├── drift_report.py
│   │   └── performance_report.py
│   └── README.md
│
├── orchestration/                         # Airflow (deployed on k3s via Helm)
│   ├── dags/
│   │   ├── dag_daily_ingest.py            # Trigger Airbyte sync + everef download
│   │   ├── dag_transform.py               # Run dbt models + tests
│   │   ├── dag_train_model.py             # Periodic retraining (weekly or drift-triggered)
│   │   ├── dag_predict.py                 # Run predictions on latest data
│   │   └── dag_monitor.py                 # Run Evidently reports, alert on drift
│   └── plugins/
│
├── dashboards/                            # BI layer
│   ├── tableau/                           # .twb or .twbx workbook files
│   └── screenshots/                       # For README and portfolio site
│
├── monitoring/                            # Infrastructure monitoring (deployed on k3s)
│   └── grafana/
│       └── dashboards/                    # JSON dashboard definitions (provisioned via Grafana API)
│
├── infra/                                 # Infrastructure as code
│   ├── terraform/                           # OpenTofu configuration (Terraform-compatible)
│   │   ├── proxmox/                       # VM provisioning (bpg/proxmox provider)
│   │   │   ├── main.tf                    # Provider config (bpg/proxmox), backend (local state)
│   │   │   ├── vms.tf                     # 3 k3s VMs: one per Proxmox node, cloud-init, static IPs
│   │   │   ├── templates.tf               # Cloud-init template download + configuration
│   │   │   ├── variables.tf               # VLAN IDs, IP ranges, VM specs, SSH keys
│   │   │   ├── outputs.tf                 # VM IPs (consumed by Ansible inventory)
│   │   │   └── README.md                  # Prerequisites: API token, cloud-init template, NFS datastore
│   │   └── snowflake/                     # Cloud-readiness proof (IaC only, not kept live)
│   │       ├── main.tf                    # Provider config, backend
│   │       ├── warehouses.tf              # XS for transforms, S for ML training
│   │       ├── databases.tf               # raw, staging, marts, ml_features schemas
│   │       ├── roles.tf                   # loader, transformer, reader roles with least-privilege grants
│   │       ├── variables.tf
│   │       ├── outputs.tf
│   │       └── README.md                  # Instructions: how to terraform plan/apply against trial
│   ├── ansible/                           # VM configuration + k3s bootstrap
│   │   ├── inventory/
│   │   │   └── hosts.yml                  # k3s server nodes (all 3 are server + workload nodes)
│   │   ├── playbooks/
│   │   │   ├── k3s-init.yml               # Bootstrap 3-node k3s HA cluster (embedded etcd)
│   │   │   ├── k3s-upgrade.yml            # Rolling k3s version upgrades
│   │   │   └── nfs-client.yml             # Install NFS utils, verify TrueNAS mount
│   │   ├── roles/                         # Ansible roles for k3s setup, prereqs, storage
│   │   └── README.md                      # Sequencing: terraform apply → ansible k3s-init → helm deploys
│   ├── helm/                              # Helm values overrides for all k3s-deployed services
│   │   ├── airbyte-values.yaml            # Airbyte Helm chart V2; resource limits for constrained RAM
│   │   ├── airflow-values.yaml            # Airflow Helm chart; DAG git-sync, executor config
│   │   ├── mlflow-values.yaml             # MLflow tracking server; NFS-backed artifact store
│   │   ├── grafana-values.yaml            # Grafana; dashboard provisioning, VictoriaMetrics datasource
│   │   ├── victoriametrics-values.yaml    # VictoriaMetrics single-node; retention, scrape configs
│   │   └── README.md                      # Helm install/upgrade commands for each service
│   ├── k8s/                               # Raw Kubernetes manifests (non-Helm resources)
│   │   ├── namespaces.yaml                # Namespace definitions: data, ml, monitoring
│   │   ├── nfs-pv.yaml                    # PersistentVolume + StorageClass for TrueNAS NFS
│   │   ├── metallb-config.yaml            # MetalLB IP address pool (outside DHCP range)
│   │   └── README.md
│   ├── Makefile                           # Common commands: make vms, make cluster, make deploy-all, etc.
│   └── README.md                          # Full bootstrap guide: Terraform → Ansible → k8s base → Helm
│
├── pyproject.toml                         # Python project config (dependencies, linting, formatting)
└── .github/
    └── workflows/
        ├── ci.yml                         # Lint, type-check, dbt compile, dbt test (on PR)
        └── cd.yml                         # Deploy model artifact (on merge to main)
```

## Deployment Strategy

### Platform

- **Everything runs on a 3-node k3s cluster** deployed across a Proxmox homelab (3 mini PCs, ~13 GB usable RAM each, ~39 GB total).
- **All 3 nodes are k3s server nodes** with workload scheduling enabled (no dedicated workers). k3s HA uses embedded etcd, which requires an odd number of server nodes.
- **Shared storage** is provided by TrueNAS NFS, mounted as a Kubernetes PersistentVolume. The DuckDB database file, model artifacts, and Airflow DAGs live on NFS.
- **Service exposure** uses MetalLB to assign stable LAN IPs from a reserved range (outside DHCP pool). The existing reverse proxy routes to these IPs.

### IaC Layers

Infrastructure is provisioned in three sequential layers:

1. **OpenTofu (bpg/proxmox provider):** Provisions 3 Ubuntu VMs (one per Proxmox node) from a cloud-init template. Injects SSH keys, static IPs on the appropriate VLAN, and hostnames. State is local. This OpenTofu project lives in `infra/terraform/proxmox/` and is scoped exclusively to the EVE project VMs — homelab base infrastructure (DNS containers, reverse proxy, Proxmox cluster config) is managed separately and is not in this repo.
2. **Ansible (k3s-io/k3s-ansible):** Configures the 3 VMs and bootstraps a k3s HA cluster with embedded etcd. Installs NFS client utilities and verifies TrueNAS connectivity. Generates a kubeconfig for `kubectl` and Helm access from the dev workstation.
3. **Helm + kubectl:** Deploys all application services into the k3s cluster. Airbyte uses Helm chart V2. Airflow, MLflow, Grafana, and VictoriaMetrics each have their own Helm values files in `infra/helm/`. Base Kubernetes resources (namespaces, NFS PersistentVolume, MetalLB config) are applied via raw manifests in `infra/k8s/`.

### Snowflake Cloud-Readiness

- **Snowflake OpenTofu** (`infra/terraform/snowflake/`) exists to prove cloud-readiness. Run `tofu plan` during the 30-day trial window, record a screencast of the output, then let the trial expire. The code remains valid IaC.
- **MotherDuck** is an option as a sustainable cloud middle-ground (free tier, DuckDB-compatible). Consider as an alternative to keeping Snowflake live.

### Budget

- **Target:** $0/month in steady state (all self-hosted on existing hardware).
- **Absolute max:** $5/month (only if a cloud component like MotherDuck is added).

### RAM Budget (approximate, ~39 GB total)

| Component              | Estimated Memory | Notes                                       |
|------------------------|------------------|---------------------------------------------|
| k3s overhead (×3)      | ~1.5 GB          | ~512 MB per server node                     |
| Airbyte                | 6–8 GB           | Largest consumer; tune resource limits      |
| Airflow                | 2–3 GB           | Webserver + scheduler + worker              |
| MLflow                 | 0.5–1 GB         | Tracking server only                        |
| Grafana                | 0.5 GB           | Lightweight                                 |
| VictoriaMetrics        | 0.5–1 GB         | Single-node mode                            |
| DuckDB (via pods)      | 1–2 GB           | Depends on query workload                   |
| BentoML                | 0.5–1 GB         | Model serving                               |
| Evidently              | 0.5 GB           | Runs periodically, not always resident      |
| **Headroom**           | **~20–24 GB**    | Available for sync jobs, spikes, OS caches  |

Resource requests and limits must be set in every Helm values file. Monitor for OOMKills and pod evictions early.

## Coding Conventions

- **Python:** Use `pyproject.toml` for all config. Format with `ruff`. Type hints encouraged. Utilize `uv`.
- **SQL (dbt):** Lowercase keywords, CTEs over subqueries, one model per file, descriptive model names with prefix convention (`stg_`, `int_`, `mart_`, `feat_`).
- **OpenTofu:** Standard HCL formatting (`tofu fmt`). One resource type per file.
- **Docker:** Multi-stage builds where applicable. Pin image versions.
- **Git:** Conventional commits. Feature branches off `main`. PRs required.
- **Mise:** Use `mise` to handle all tooling.

## Common Agent Tasks

When asked to work on this project, these are typical requests and where to look:

- **"Add a new data source"** → `ingestion/`, then add staging model in `transform/models/staging/`, then wire into `orchestration/dags/dag_daily_ingest.py`.
- **"Add a new feature for ML"** → `transform/models/ml_features/` (SQL-side) or `ml/training/feature_engineering.py` (Python-side).
- **"Write a dbt test"** → `transform/tests/` for custom singular tests, or add to schema YAML in the relevant model directory.
- **"Add a new Airflow DAG"** → `orchestration/dags/`. Follow existing DAG patterns. Use `@dag` decorator style.
- **"Set up a new monitoring dashboard"** → `monitoring/grafana/dashboards/` for JSON definitions.
- **"Write OpenTofu for Snowflake"** → `infra/terraform/`. Use Snowflake provider v2.x. Follow existing resource-per-file convention.
- **"Update documentation"** → `docs/` for architecture, data dictionary, model card. `README.md` for setup/overview.
