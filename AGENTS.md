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
| Cloud-readiness | **Snowflake** (Terraform only) | IaC code proves cloud deployment path; not kept live (trial expires in 30 days) |
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
├── orchestration/                         # Airflow
│   ├── dags/
│   │   ├── dag_daily_ingest.py            # Trigger Airbyte sync + everef download
│   │   ├── dag_transform.py               # Run dbt models + tests
│   │   ├── dag_train_model.py             # Periodic retraining (weekly or drift-triggered)
│   │   ├── dag_predict.py                 # Run predictions on latest data
│   │   └── dag_monitor.py                 # Run Evidently reports, alert on drift
│   ├── plugins/
│   └── docker-compose.yml                 # Local Airflow (webserver, scheduler, worker, postgres)
│
├── dashboards/                            # BI layer
│   ├── tableau/                           # .twb or .twbx workbook files
│   └── screenshots/                       # For README and portfolio site
│
├── monitoring/                            # Infrastructure monitoring
│   ├── grafana/
│   │   └── dashboards/                    # JSON dashboard definitions (provisioned via Grafana API)
│   ├── victoriametrics/
│   │   └── config.yml
│   └── docker-compose.monitoring.yml
│
├── infra/                                 # Infrastructure as code + local orchestration
│   ├── docker-compose.yml                 # Full local stack (Airbyte, DuckDB, Airflow, MLflow, etc.)
│   ├── Makefile                           # Common commands: make setup, make ingest, make transform, etc.
│   └── terraform/                         # Snowflake cloud deployment (IaC proof, not kept live)
│       ├── main.tf                        # Provider config, backend
│       ├── warehouses.tf                  # XS for transforms, S for ML training
│       ├── databases.tf                   # raw, staging, marts, ml_features schemas
│       ├── roles.tf                       # loader, transformer, reader roles with least-privilege grants
│       ├── variables.tf
│       ├── outputs.tf
│       └── README.md                      # Instructions: how to terraform plan/apply against trial
│
├── pyproject.toml                         # Python project config (dependencies, linting, formatting)
└── .github/
    └── workflows/
        ├── ci.yml                         # Lint, type-check, dbt compile, dbt test (on PR)
        └── cd.yml                         # Deploy model artifact (on merge to main)
```

## Deployment Strategy

- **Everything runs locally / self-hosted** on homelab or a powerful PC. No cloud costs.
- **Snowflake Terraform** exists to prove cloud-readiness. Run `terraform plan` during the 30-day trial window, record a screencast of the output, then let the trial expire. The code remains valid IaC.
- **MotherDuck** is an option as a sustainable cloud middle-ground (free tier, DuckDB-compatible). Consider as an alternative to keeping Snowflake live.
- **Budget constraint:** Ideally $0/month in steady state. Absolute max $5/month.

## Coding Conventions

- **Python:** Use `pyproject.toml` for all config. Format with `ruff`. Type hints encouraged. Utilize `uv`.
- **SQL (dbt):** Lowercase keywords, CTEs over subqueries, one model per file, descriptive model names with prefix convention (`stg_`, `int_`, `mart_`, `feat_`).
- **Terraform:** Standard HCL formatting (`terraform fmt`). One resource type per file.
- **Docker:** Multi-stage builds where applicable. Pin image versions.
- **Git:** Conventional commits. Feature branches off `main`. PRs required.

## Common Agent Tasks

When asked to work on this project, these are typical requests and where to look:

- **"Add a new data source"** → `ingestion/`, then add staging model in `transform/models/staging/`, then wire into `orchestration/dags/dag_daily_ingest.py`.
- **"Add a new feature for ML"** → `transform/models/ml_features/` (SQL-side) or `ml/training/feature_engineering.py` (Python-side).
- **"Write a dbt test"** → `transform/tests/` for custom singular tests, or add to schema YAML in the relevant model directory.
- **"Add a new Airflow DAG"** → `orchestration/dags/`. Follow existing DAG patterns. Use `@dag` decorator style.
- **"Set up a new monitoring dashboard"** → `monitoring/grafana/dashboards/` for JSON definitions.
- **"Write Terraform for Snowflake"** → `infra/terraform/`. Use Snowflake provider v2.x. Follow existing resource-per-file convention.
- **"Update documentation"** → `docs/` for architecture, data dictionary, model card. `README.md` for setup/overview.
