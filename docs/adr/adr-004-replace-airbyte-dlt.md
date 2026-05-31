---
status: accepted
date: 2026-04-10
tags:
  - infra
  - tools
amended:
  - 2026-04-13
  - 2026-05-10
---

# ADR-004 - Replace Airbyte with Python Dataset-Publishing Ingestion

## Context

Airbyte was the original EL tool in the stack, chosen early for connector breadth,
resume relevance, and UI-based sync management. A later re-evaluation found that it
was a poor fit for the actual data sources, cluster budget, and desired publication
contract.

## Decision

Remove Airbyte entirely. Use Python ingestion jobs orchestrated by Airflow to fetch
source data and publish DuckLake tables backed by Parquet data files.

The planned pipeline contract becomes:

`Airflow -> dlt dataset writer/publisher -> DuckLake raw/bronze tables -> dbt reads canonical table state through an attached DuckLake alias in transient local DuckDB compute -> curated DuckLake tables and/or transient local DuckDB work DB`

This ADR is about the ingestion approach, not a runtime implementation. It defines
the contract the future ingestion code must follow.

## Rationale

Three problems compounded to make Airbyte a poor fit:

1. **Disproportionate resource consumption.** Airbyte would be one of the largest RAM
   consumers in a cluster with a tight homelab resource budget, despite the project
   only needing to download CSV archives and poll a public REST API.
2. **Overengineered for the real source set.** The project has exactly two source
   families: everef.net bulk archives and the EVE ESI API. Both are well-served by
   explicit Python jobs with rate limiting, retries, and publication semantics.
3. **Poor fit for the target table contract.** The project is standardizing on
   single-writer publication of DuckLake table state with explicit replacement scopes
   and contracts. Airbyte's destination-centric model is less aligned with that
   contract than explicit ingestion code.

## Contract Changes

- Airflow schedules ingestion jobs and publication steps directly.
- Ingestion jobs write candidate output, validate, then commit DuckLake table changes
  for the intended replacement scope.
- Raw tables are published to shared storage as DuckLake-backed Parquet data files, not
  merged into a shared mutable DuckDB database file.
- dbt reads canonical table state through an attached DuckLake alias in transient local
  DuckDB compute and may materialize final curated DuckLake outputs directly while
  keeping upstream work tables local.

## What This Does Not Change

- k3s remains the deployment platform.
- The three-layer IaC sequence (Terraform -> Ansible -> Helm/kubectl) is unchanged.
- The rest of the application stack remains in place.
- Snowflake remains a cloud-readiness proof, not the steady-state runtime store.

## Portfolio Framing

Custom ingestion code better demonstrates extraction logic, source-specific error
handling, rate limiting, schema awareness, and publication design than configuring a
generic sync platform. It makes the dataset contract explicit and reviewable in code
and documentation.

## Alternatives Considered

- *PyAirbyte:* Lighter than the full platform, but still not the right abstraction for
  explicit dataset publication.
- *Keep Airbyte and publish through a separate post-processing step:* Adds complexity
  while keeping the heaviest part of the stack.
- *Switch to a hosted warehouse and keep Airbyte:* Conflicts with the cost target and
  weakens the self-hosted architecture story.

## Amendments

- 2026-04-13 - Updated for the Parquet publication contract
  - This ADR originally described Python/dlt jobs that loaded into DuckDB before dbt
    transforms. Following ADR-007, the ingestion flow is now documented as publishing
    file-backed datasets, with DuckDB only as local or transient compute when needed.
    ADR-008 later refined this into DuckLake table publication over Parquet data files.

- 2026-05-10 - Updated for DuckLake publication contract
  - ADR-008 adopts DuckLake as the canonical table format. dlt ingestion publishes
    table changes with merge/delete-insert semantics where needed, while Parquet remains
    the physical data file format.
