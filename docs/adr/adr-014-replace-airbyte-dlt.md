---
status: accepted
date: 2026-04-10
tags: 
  - infra
  - tools
amended: []
---

# ADR 014 - Replace Airbyte with Python/dlt Ingestion Scripts

## Context

Airbyte was the original EL (Extract-Load) tool in the stack, chosen early in the project for its 
connector ecosystem, job description relevancy, and UI-based sync management. However, a re-evaluation 
identified three compounding problems that made Airbyte untenable for this project's specific constraints.

## Decision

Remove Airbyte entirely. Replace it with Python ingestion scripts (using `dlt` or custom code) that run 
directly inside Airflow DAGs. The `infra/helm/airbyte-values.yaml` file is removed. The `ingestion/` 
directory's existing Python scripts become the production ingestion code rather than feeders into an Airbyte 
custom connector.

## Rationale

Three problems compounded to make Airbyte a poor fit:

1. **DuckDB destination incompatibility on Kubernetes.** Airbyte's own documentation explicitly states that 
   local file-based databases will not work in Airbyte Cloud or Kubernetes, and recommends using MotherDuck 
   instead. Since the project's warehouse is DuckDB on NFS-backed PersistentVolumes and the deployment target 
   is k3s, these are fundamentally incompatible according to Airbyte's own docs. Switching to MotherDuck would 
   conflict with the $0/month budget target.
2. **Disproportionate resource consumption.** The RAM budget table allocated 6–8 GB to Airbyte - the single 
   largest consumer in the cluster, exceeding all other services combined. On a cluster with ~39 GB total usable 
   RAM (and ~1.5 GB consumed by k3s overhead alone), Airbyte would claim approximately 15–20% of total resources 
   for what amounts to downloading CSVs and polling a REST API. Airbyte recommends a minimum of 4 CPUs and 8 GB 
   RAM for standard operation, and the project had previously identified that "the honest risk isn't learning 
   k3s - it's the time sink of debugging Airbyte's Helm chart on a memory-constrained cluster."
3. **Overengineered for the actual data sources.** The project has exactly two data sources: everef.net (bulk 
   CSV downloads) and the EVE ESI API (REST API with 300 req/min rate limit). Neither requires Airbyte's connector 
   ecosystem, change data capture, or sync scheduling infrastructure. Python scripts with rate limiting, error 
   handling, and incremental loading - orchestrated by Airflow - are a more appropriate tool for this scope.

**What this changes:**

- Airflow DAGs call ingestion scripts directly (Python tasks or KubernetesPodOperator). The pipeline becomes: 
  Airflow DAG triggers Python/dlt script -> loads to DuckDB -> dbt transforms.
- The `infra/helm/` directory loses the Airbyte chart and its dependencies (Postgres, Redis, Temporal).
- Approximately 6–8 GB of cluster RAM is freed for other services and headroom.
- Sync observability moves to Airflow task metrics and logs, consistent with how the rest of the pipeline is 
  monitored.

**What this does not change:**

- k3s remains the deployment platform (see revised ADR-002 for updated justification).
- The three-layer IaC sequence (Terraform -> Ansible -> Helm) is unchanged.
- All other stack components (Airflow, dbt, MLflow, BentoML, Evidently, VictoriaMetrics, Grafana, DuckDB, 
  Tableau) are unaffected.
- The Snowflake Terraform proof and MotherDuck middle-ground option are unchanged.

**Portfolio framing:**

Writing custom ingestion code with dlt demonstrates deeper data engineering skill than configuring Airbyte's 
UI - it shows understanding of extraction logic, rate limiting, incremental loading, and schema management at 
the code level. This is noted as the approach that dlt takes: treating data pipelines as Python applications 
that can be developed, tested, and maintained using familiar software engineering practices.

## Alternatives considered

- *PyAirbyte:* A lighter-weight Python library that provides Airbyte connector access without the full platform. 
  Would solve the resource problem but not the DuckDB-on-Kubernetes incompatibility.
- *Keep Airbyte, switch warehouse to MotherDuck:* Would solve the destination incompatibility but conflicts with 
  the $0/month budget target and adds an external dependency.
- *Keep Airbyte, switch to Docker Compose:* Would solve the Kubernetes destination issue, but would fragment 
  the deployment across two orchestration systems (k3s for everything else, Docker Compose for Airbyte) and still 
  consume 6–8 GB RAM. It's also not directly supported.

