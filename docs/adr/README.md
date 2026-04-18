# Architectural Decision Records

This directory contains the project's Architectural Decision Records (ADRs).

## What Lives Here

- one Markdown file per decision
- filenames in the form `adr-###-short-name.md`
- decisions covering data sources, storage architecture, infrastructure sequencing,
  validation workflow, and platform/tooling choices

## Current Scope

The checked-in ADRs document the major design choices behind the current repo,
including:

- data source selection for market history and order data
- dlt replacing Airbyte for ingestion
- k3s on Proxmox homelab infrastructure
- kube-vip and k3s networking choices
- Airflow DAG delivery via `git-sync` in homelab `k3s`
- external PostgreSQL for Airflow metadata
- deferred PgBouncer decision for Airflow metadata
- Parquet on shared NFS as the system of record
- the prohibition on a cluster-shared writable DuckDB file

## Reading Order

Start with the higher-impact architecture records if you need project context quickly:

1. `adr-014-replace-airbyte-dlt.md`
2. `adr-015-kube-vip-daemon-endpoint.md`
3. `adr-016-parquet-system-of-record.md`

Earlier ADRs provide the historical decision trail that led to the current contract.
