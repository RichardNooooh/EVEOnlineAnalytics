# Architectural Decision Records

This directory contains the project's Architectural Decision Records (ADRs).

## What Lives Here

- one Markdown file per decision
- filenames in the form `adr-###-short-name.md`
- analytics workload decisions owned by `eve-market-analytics`

## Current Scope

The checked-in ADRs document the major analytics-repository design choices for
`eve-market-analytics`, including:

- workload versus platform repository boundaries
- market data source selection
- workload tool choices and explicit exclusions
- Python + dlt ingestion replacing Airbyte
- DuckDB as local/transient compute rather than shared durable storage
- DuckLake as the canonical analytical table format over Parquet data files
- raw source-file ledger backend selection for local and deployed ingestion runs
- ML problem framing and deferred streaming scope

## Reading Order

Start with the higher-impact workload records if you need project context quickly:

1. `adr-001-split-workload-and-platform-repositories.md`
2. `adr-004-replace-airbyte-dlt.md`
3. `adr-007-ducklake-canonical-table-format.md`
4. `adr-008-raw-file-ledger-backends.md`
5. `adr-006-parquet-system-of-record.md`
6. `adr-002-data-sources.md`

Earlier ADRs provide the historical decision trail that led to the current contract.
