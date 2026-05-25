---
status: accepted
date: 2026-05-10
tags:
  - data
  - storage
  - ducklake
  - dlt
amended: []
---

# ADR-007 - DuckLake as the Canonical Lakehouse Table Format

## Context

ADR-006 established a Parquet dataset contract on shared storage and rejected a
cluster-shared writable DuckDB database file. That decision made the durable analytical
state file-oriented and kept DuckDB in its proper role as local or transient compute.

The ingestion design now needs stronger table semantics than plain filesystem Parquet
can provide on its own. Everef market-history files are daily historical source files,
and those files may be revised after initial publication as additional source data is
discovered. The project needs to reload one or more affected market dates without
appending duplicate rows and without replacing the entire historical table.

Plain Parquet files remain a good physical storage format, but plain filesystem Parquet
alone lacks table-level update, delete, merge, and transaction semantics. dlt's
filesystem destination does not provide true merge semantics for plain Parquet; merge
effectively falls back to append. That is a poor fit for revised daily files where the
correct replacement scope is one or more market dates.

dlt's DuckLake destination supports lakehouse-style table storage over files with SQL
catalog metadata and supports merge strategies including delete-insert. DuckLake also
aligns well with the project's DuckDB/dbt-oriented local analytics stack. PostgreSQL
already exists in the infrastructure plan and can later serve as a production-grade
DuckLake catalog, while local development can start with a local DuckLake catalog.

## Decision

Adopt **DuckLake as the canonical lakehouse table format** for the project's analytical
storage layer.

The refined storage contract is:

- DuckLake tables are the canonical analytical table storage contract.
- Parquet remains the physical data file format underneath the table format.
- Plain filesystem Parquet alone is not the long-term canonical table storage format.
- dlt loads Everef market-history data into DuckLake using merge/delete-insert
  semantics.
- Existing CSV `date` is the replacement unit for revised Everef daily files.
- Market-history loads use a composite primary key of `date`, `region_id`, and
  `type_id` where applicable.
- Iceberg remains a possible future cloud or resume extension, not the initial
  implementation target.
- Delta Lake is not used unless the project later intentionally shifts toward a
  Databricks/Spark-oriented architecture.

This ADR refines ADR-006. It does not reintroduce a cluster-shared writable `.duckdb`
file. DuckDB remains local or transient compute, while DuckLake provides table metadata
and transaction semantics over data files.

## Operational Notes

- A local SQLite DuckLake catalog is acceptable only for local smoke testing and early
  local development.
- A PostgreSQL DuckLake catalog is required for production-style or mounted/shared
  DuckLake storage runs.
- Mounted/shared DuckLake storage with a SQLite catalog is rejected by ingestion
  publisher configuration.
- Data files remain Parquet files stored under the lakehouse table format.
- Production-style data files may live on TrueNAS/NFS initially, with MinIO or another
  S3-compatible store remaining a possible later backing store.
- dbt integration should be validated separately from dlt's DuckLake destination;
  dbt-duckdb may read raw DuckLake tables from local/transient DuckDB compute and
  materialize final curated DuckLake tables directly.

## Consequences

### Positive

- Revised Everef daily files can be represented as replacement operations for affected
  market dates instead of append-only duplicate rows.
- Table-level merge/delete semantics are explicit and testable.
- The analytical storage layer remains file-backed and compatible with the existing
  local DuckDB orientation.
- PostgreSQL can be reused later as a production-grade catalog service instead of
  adding a new metadata database technology.
- The decision keeps the implementation scope narrower than adopting a Spark-oriented
  lakehouse stack.

### Negative

- The storage contract now includes a catalog dependency, not only files and manifests.
- Operators must back up and manage the DuckLake catalog in addition to the data files.
- curated dbt publication becomes visible when model materialization completes; dbt data
  tests still run afterward unless a separate promotion boundary is added.
- Existing documents and code that describe plain Parquet as the canonical storage
  contract must be updated during the implementation migration.

## Alternatives Considered

- *Plain Parquet:* Rejected as the long-term canonical table storage format. It remains
  the physical file format, but plain filesystem Parquet alone does not provide the
  update, delete, merge, and transaction semantics needed for revised Everef daily
  files.
- *Delta Lake:* Rejected for now because it is most compelling in a Databricks/Spark
  architecture. The project is DuckDB/dbt-oriented and does not currently need to adopt
  Spark to solve this problem.
- *Apache Iceberg:* Deferred. Iceberg is a strong general lakehouse format and remains a
  possible future cloud or resume extension, but it is more infrastructure than the
  initial homelab implementation needs.
- *Append-only bronze plus manual reconciliation:* Rejected because it pushes source
  correction semantics into later query or transform logic. The ingestion layer should
  make the replacement unit explicit and prevent stale duplicate rows in the canonical
  table state.
