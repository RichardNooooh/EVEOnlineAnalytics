---
status: accepted
date: 2026-05-10
tags:
  - data
  - storage
  - ducklake
  - dlt
amended:
  - 2026-05-27
  - 2026-09-05
---

# ADR-008 - DuckLake as the Canonical Lakehouse Table Format

## Context

ADR-007 established a Parquet dataset contract on shared storage and rejected a
cluster-shared writable DuckDB database file. That decision made the durable analytical
state file-oriented and kept DuckDB in its proper role as local or transient compute.

Everef market history is append-only by `(date, region_id, type_id)`. Everef can
republish a daily archive to add previously missing keys; it does not change
market values for existing keys or remove them. The
[saved-archive comparison](../../experiments/everef/market_history_revisions/analysis.ipynb)
for market date 2026-10-11 found 55,881 added keys, zero changed market rows,
and zero removals across 27 snapshots. A changed archive timestamp, checksum, or
row count is not evidence of a row correction.

The project needs to publish more complete versions of individual market dates
without duplicating their previously published rows or rebuilding the entire
history.

Plain Parquet files remain a good physical storage format, but plain filesystem Parquet
alone lacks table-level update, delete, merge, and transaction semantics. dlt's
filesystem destination does not provide true merge semantics for plain Parquet; merge
effectively falls back to append. Appending a complete daily archive again would
duplicate every key already published for that date.

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
- The Everef market-history publisher loads DuckLake using atomic source-date
  partition replacement.
- Existing CSV `date`, `region_id`, and `type_id` are validated as the unique row key
  before partition replacement.
- Market-history loads use a composite primary key of `date`, `region_id`, and
  `type_id` where applicable.
- Iceberg remains a possible future cloud or resume extension, not the initial
  implementation target.
- Delta Lake is not used unless the project later intentionally shifts toward a
  Databricks/Spark-oriented architecture.

This ADR refines ADR-007. It does not reintroduce a cluster-shared writable `.duckdb`
file. DuckDB remains local or transient compute, while DuckLake provides table metadata
and transaction semantics over data files.

## Operational Notes

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

## Amendment (2026-05-27)

The publisher switched to insert-new-by-key, so reprocessing a daily archive
added newly available rows without rewriting existing keys.

## Amendment (2026-09-05)

The publisher switched from insert-new-by-key to replacing the source-date
partition. It validates that every candidate row belongs to the requested date
and that keys are unique, then atomically replaces that date's rows. Partition
replacement is our publication strategy, not a claim that Everef changes
existing market rows.

## Consequences

### Positive

- Republished Everef daily files can refresh the affected dates atomically
  without duplicating keys.
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
  the physical file format, but plain filesystem Parquet alone does not provide
  the table-level transactions used to publish a consistent source-date partition.
- *Delta Lake:* Rejected for now because it is most compelling in a Databricks/Spark
  architecture. The project is DuckDB/dbt-oriented and does not currently need to adopt
  Spark to solve this problem.
- *Apache Iceberg:* Deferred. Iceberg is a strong general lakehouse format and remains a
  possible future cloud or resume extension, but it is more infrastructure than the
  initial homelab implementation needs.
- *Append complete archive versions and deduplicate downstream:* Rejected
  because it pushes key reconciliation into every reader. The ingestion layer
  should publish one row per market-history key.
