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
  - 2026-05-22
---

# ADR-003 - Tools Used and Not Used

## Context

Every tool in the stack must have a distinct, non-overlapping purpose and a
one-sentence justification for its inclusion over alternatives. Deliberate exclusions
and the reasoning behind them are themselves part of the architecture record.

This ADR is the canonical taxonomy for the stack.

After the workload/platform repository split, this ADR records **workload-owned
analytics tooling only**. Platform implementation choices such as infrastructure
provisioning, cluster runtime, infra monitoring, and storage products belong in
`homelab-data-platform`, not here.

## Decision

The stack is defined by the two tables below.

### Tools in use

| Layer | Tool | Justification |
|---|---|---|
| **Orchestration** | Airflow | Industry-standard DAG orchestrator for ingestion, dbt, and ML jobs. |
| **Ingestion** | Python + dlt | Lightweight, code-first ingestion approach for everef.net archives and the ESI API. See ADR-004. |
| **Storage** | DuckLake over Parquet files | Shared analytical storage holds DuckLake data files, contracts, artifacts, and logs. DuckLake catalog metadata is durable state and should use PostgreSQL in production-style deployments. See ADR-006 and ADR-007. |
| **Compute** | DuckDB (local or transient only) | Embedded analytical engine used for local development and single-writer batch jobs. DuckDB databases are scratch state, not cluster-shared persistent storage. See ADR-006. |
| **Transformation** | dbt | SQL-first transformation with built-in lineage, testing, and documentation; planned to read DuckLake-backed table state through a validated DuckLake/DuckDB handoff. |
| **BI** | Evidence OSS | Static BI and case-study site built from markdown, SQL, and version-controlled data outputs; self-hosted builds fit the portfolio publishing model without adding another durable analytics store. |
| **ML Experiment Tracking** | MLflow | Tracks experiments, parameters, metrics, and model artifacts; integrates cleanly with Python training scripts and serves as the model registry. |
| **ML Serving** | BentoML | Packages trained models as REST APIs with health checks and rolling restarts. |
| **Model Monitoring** | Evidently | Generates data drift and model performance reports as part of the analytics workload. |
| **Cloud Proof - Managed Warehouse** | Snowflake (trial only) | Managed warehouse proof-of-concept kept as a scoped analytics-side compatibility path rather than a steady-state runtime. |
| **Tool Version Management** | mise | Manages analytics-scoped CLI tools such as Python, `uv`, dbt, `ruff`, and local validation utilities via `mise.toml`. Platform-only tooling belongs in `homelab-data-platform`. |
| **Local Validation** | pre-commit | Runs repo-scoped validation before commit. |
| **CI/CD** | GitHub Actions + GHCR | Runs validation workflows and publishes trusted ingestion container images. |

### Tools explicitly not used

| Tool | Reason for Exclusion |
|---|---|
| **Airbyte** | Removed after evaluation. The project has two well-defined source types, does not need Airbyte's platform overhead, and is moving toward explicit single-writer dataset publication rather than syncs into a mutable destination warehouse. See ADR-004. |
| **Great Expectations** | Overlaps with dbt tests. dbt tests cover schema, business logic, freshness, and custom assertions sufficiently for this project's scope. |
| **DVC** | DuckLake tables, catalog metadata, contracts, manifests, and MLflow already cover persisted analytical data and model artifacts. DVC would add a parallel versioning system with no clear incremental benefit at this scale. |
| **Tableau** | Evidence OSS is the sole BI and case-study publishing surface. Tableau would duplicate the reporting layer and split effort across two presentation stacks. |
| **PowerBI** | Evidence OSS is the sole BI and case-study publishing surface. Adding PowerBI provides no incremental portfolio value and splits effort. |

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

- 2026-05-22 - Replace Tableau with Evidence OSS for BI delivery
  - The BI layer now uses Evidence OSS instead of Tableau.
  - Static site generation from markdown, SQL, and exported analytical outputs better fits
    the repo's code-first portfolio positioning and self-hosted publishing model.

- 2026-05-22 - Remove split-out platform tooling from the workload tool taxonomy
  - Following the workload/platform repository split, ADR-003 now records only
    workload-owned analytics tooling.
  - Platform tooling and implementation-specific products such as infra monitoring,
    storage vendors, and infrastructure automation are left to `homelab-data-platform`.
