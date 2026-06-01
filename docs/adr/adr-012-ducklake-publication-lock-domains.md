---
status: accepted
date: 2026-05-31
tags:
  - ducklake
  - concurrency
  - ingestion
  - postgres
---

# ADR-012 - DuckLake Publication Lock Domains And Explicit Raw Bootstrap

## Context

The initial raw DuckLake publisher used PostgreSQL advisory locks keyed directly by
semantic publication scope strings and created the raw schema plus shared support table
inside the normal writer enter path.

That shape kept single-writer behavior simple, but it mixed two separate concerns:

- semantic publication-scope naming for publication tracking
- physical DuckLake mutation domains that must serialize concurrent writers against the
  same raw table and provenance table set

It also left routine schema and support-table DDL on the hot publication path and kept
all raw provenance in a single `raw_source_objects` table, which increases contention
and obscures dataset-local lineage.

DuckLake table state is the canonical contract, but concurrent multi-client publication
still depends on an external coordination mechanism. In this project that mechanism is
PostgreSQL advisory locks over stable DuckLake lock domains, with PostgreSQL also acting
as the required durable DuckLake catalog backend for mounted/shared multi-client use.

Relevant upstream DuckLake references:

- Transactions: <https://ducklake.select/docs/stable/duckdb/advanced_features/transactions.html>
- Conflict resolution: <https://ducklake.select/docs/stable/duckdb/advanced_features/conflict_resolution.html>
- Choosing a catalog database: <https://ducklake.select/docs/stable/duckdb/usage/choosing_a_catalog_database.html>
- Recommended maintenance: <https://ducklake.select/docs/stable/duckdb/maintenance/recommended_maintenance.html>

## Decision

Adopt explicit DuckLake advisory lock domains and an explicit raw bootstrap step.

The first stable lock domains are:

- `ducklake:migration`
- `ducklake:maintenance`
- `ducklake:raw:raw_market_history`
- `ducklake:raw:raw_market_orders`
- `ducklake:raw:raw_fuzzwork_orders`
- `ducklake:raw:references`
- `ducklake:support:raw_market_history_objects`
- `ducklake:support:raw_market_orders_objects`
- `ducklake:support:raw_fuzzwork_orders_objects`
- `ducklake:support:raw_reference_objects`

Lock acquisition order is fixed by rank:

1. migration
2. maintenance
3. data/publication domain
4. support/provenance domain

Lexical ordering is only allowed within the same rank.

`PublicationContext.publication_scope` remains the semantic published-slice name used by
the raw-file ledger and publication tracking. It is not replaced by physical lock-domain
names.

Raw provenance is now dataset-scoped:

- `raw_market_history_objects`
- `raw_market_orders_objects`
- `raw_fuzzwork_orders_objects`
- `raw_reference_objects`

The old shared `raw_source_objects` table is retired as a breaking change. Legacy rows
are not migrated.

Raw schema and provenance-table bootstrap move out of the normal writer enter path into
an explicit CLI entrypoint: `eve-ingest ducklake bootstrap raw`.

## Consequences

### Positive

- Same-table raw writes remain serialized even when semantic publication scopes differ.
- Provenance contention narrows to the dataset-local support table.
- Insert-style raw writers no longer perform routine schema or table bootstrap DDL during
  normal entry.
- Reference-data tarball publication can run as one transaction, making table
  replacement all-or-nothing when the underlying DuckDB and DuckLake transaction path
  succeeds.

### Negative

- Operators must run raw bootstrap before first publication to a new raw DuckLake
  catalog/schema.
- The change is intentionally breaking for provenance-table readers.
- `REPLACE_TABLE` still uses `create or replace table` on the write path in this pass.
  Raw bootstrap now creates the known reference tables up front, but replace-style
  writes still rely on DDL semantics until a lower-risk follow-up narrows that path.
- This pass does not add general optimistic-conflict retries for DuckLake write failures;
  only external advisory serialization is relied on because broader retries were not yet
  proven safe across all writer modes.
- Maintenance should take the dedicated `ducklake:maintenance` domain and avoid overlap
  with normal writer windows, even though Airflow-level `max_active_runs` remains only an
  outer scheduling guard.
