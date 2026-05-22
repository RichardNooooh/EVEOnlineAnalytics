# Architectural Decision Records

This directory contains the project's Architectural Decision Records (ADRs).

## What Lives Here

- one Markdown file per decision
- filenames in the form `adr-###-short-name.md`
- decisions covering data sources, storage architecture, infrastructure sequencing,
  validation workflow, and platform/tooling choices

## Current Scope

The checked-in ADRs document the major design choices behind the current
analytics repository, `eve-market-analytics`, plus transitional copies of some
platform decisions that will move to or be mirrored in
`homelab-data-platform`, including:

- data source selection for market history and order data
- dlt replacing Airbyte for ingestion
- k3s on Proxmox homelab infrastructure
- kube-vip and k3s networking choices
- Airflow DAG delivery via `git-sync` in homelab `k3s`
- external PostgreSQL on a separate Proxmox VM for Airflow metadata, with possible
  later MLflow use
- deferred PgBouncer decision for Airflow metadata
- DuckLake as the canonical lakehouse table format over Parquet data files
- URL-selected raw source-file acquisition ledgers, with SQLite for direct local runs
  and PostgreSQL for deployed runtimes
- the active split between this analytics workload repository and the companion
  `homelab-data-platform` repository
- the prohibition on a cluster-shared writable DuckDB file

Platform-focused ADRs currently remain here as transition records and likely
move or mirror candidates for `homelab-data-platform`. This especially applies
to ADRs centered on VM provisioning, k3s cluster topology and networking,
infrastructure sequencing, Airflow runtime deployment patterns, and runtime
metadata-service topology.

Authoritative long-term ownership for platform ADR evolution belongs in
`homelab-data-platform`. Retained copies in this repo are historical context
during migration, not the intended permanent home for future platform design
changes.

## Reading Order

Start with the higher-impact workload records if you need project context quickly:

1. `adr-022-split-workload-and-platform-repositories.md`
2. `adr-014-replace-airbyte-dlt.md`
3. `adr-020-ducklake-canonical-table-format.md`
4. `adr-021-raw-file-ledger-backends.md`
5. `adr-016-parquet-system-of-record.md`
6. `adr-001-data-sources.md`

Earlier ADRs provide the historical decision trail that led to the current contract.
