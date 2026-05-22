---
status: accepted
date: 2026-03-26
tags:
  - tools
amended:
  - 2026-04-10
  - 2026-04-13
  - 2026-04-14
  - 2026-05-10
  - 2026-05-12
---

# ADR-003 - Tools Used and Not Used

## Context

Every tool in the stack must have a distinct, non-overlapping purpose and a
one-sentence justification for its inclusion over alternatives. Deliberate exclusions
and the reasoning behind them are themselves part of the architecture record.

This ADR is the canonical taxonomy for the stack.

## Decision

The stack is defined by the two tables below.

### Tools in use

| Layer | Tool | Justification |
|---|---|---|
| **Orchestration** | Airflow | Industry-standard DAG orchestrator for ingestion, dbt, and ML jobs. |
| **Ingestion** | Python + dlt | Lightweight, code-first ingestion approach for everef.net archives and the ESI API. See ADR-004. |
| **Storage** | DuckLake over Parquet files on TrueNAS (ZFS RAIDZ1) + NFS | Shared storage holds DuckLake data files, contracts, artifacts, and logs. DuckLake catalog metadata is durable state and should use PostgreSQL in production-style deployments. See ADR-006 and ADR-007. |
| **Compute** | DuckDB (local or transient only) | Embedded analytical engine used for local development and single-writer batch jobs. DuckDB databases are scratch state, not cluster-shared persistent storage. See ADR-006. |
| **Transformation** | dbt | SQL-first transformation with built-in lineage, testing, and documentation; planned to read DuckLake-backed table state through a validated DuckLake/DuckDB handoff. |
| **BI** | Tableau | Portfolio-standard BI tool for dashboard presentation; Tableau Public enables sharing without licensing cost. |
| **ML Experiment Tracking** | MLflow | Tracks experiments, parameters, metrics, and model artifacts; integrates cleanly with Python training scripts and serves as the model registry. |
| **ML Serving** | BentoML | Packages trained models as REST APIs with health checks and rolling restarts. |
| **Model Monitoring** | Evidently | Generates data drift and model performance reports as part of the analytics workload. |
| **Infra Monitoring** | VictoriaMetrics + Grafana | Provides dashboards for pipeline health, durations, API errors, and resource usage. |
| **Cloud Proof - Managed Warehouse** | Snowflake (via Terraform, trial only) | Cloud-readiness proof-of-concept; Terraform resource definitions are authored, `tofu plan` is screencasted during the trial window, then the trial is allowed to expire. |
| **Tool Version Management** | mise | Manages pinned versions of OpenTofu, Helm, Python, dbt, Ansible, and other CLI tools via `mise.toml`. |
| **Local Validation** | pre-commit | Runs repo-scoped validation before commit. |
| **CI/CD** | GitHub Actions + GHCR + self-hosted runners | Runs validation workflows and publishes trusted ingestion container images. |

### Tools explicitly not used

| Tool | Reason for Exclusion |
|---|---|
| **Airbyte** | Removed after evaluation. The project has two well-defined source types, does not need Airbyte's platform overhead, and is moving toward explicit single-writer dataset publication rather than syncs into a mutable destination warehouse. See ADR-004. |
| **Great Expectations** | Overlaps with dbt tests. dbt tests cover schema, business logic, freshness, and custom assertions sufficiently for this project's scope. |
| **DVC** | DuckLake tables, catalog metadata, contracts, manifests, and MLflow already cover persisted analytical data and model artifacts. DVC would add a parallel versioning system with no clear incremental benefit at this scale. |
| **PowerBI** | Tableau is the sole BI tool. Adding a second BI tool provides no incremental portfolio value and splits effort. |
| **Terratest** | The current analytics repo does not need a separate IaC test framework for its scoped cloud-readiness proof. |

## Amendments

- 2026-04-10 - Airbyte formally moved to "not used"
  - Airbyte was included in the original stack as the EL tool and appeared in the
    "Tools in use" table. Following the evaluation documented in ADR-004, Airbyte
    was removed from the stack entirely and moved to the "Tools explicitly not
    used" table. The original inclusion is preserved in git history.

- 2026-04-13 - Storage and compute were separated
  - The earlier taxonomy implicitly treated DuckDB as both storage and compute.
    Following ADR-006, the stack now distinguishes shared storage from local or
    transient compute. This was later refined by ADR-007 so DuckLake tables are the
    canonical analytical table contract and Parquet is the physical file format.
    DuckDB remains in the stack as a local analytical engine only.

- 2026-04-14 - Validation tooling was documented explicitly
  - `pre-commit` is part of the documented local validation path.
  - GitHub Actions and GHCR are recorded as the CI and image-publishing path.

- 2026-05-10 - Refine storage contract for DuckLake
  - ADR-007 adopts DuckLake as the canonical analytical table format. Parquet remains
    the physical data file format rather than the table contract.

- 2026-05-12 - Split image publishing from self-hosted validation runners
  - The ingestion image workflow uses GitHub-hosted `ubuntu-latest` runners and publishes
    trusted `master` builds to GHCR.
