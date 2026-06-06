# ingestion/AGENTS.md

Read this when changing extraction, source clients, dlt pipelines, dataset publishers,
or ingestion tests.

## Read First

- `../AGENTS.md`
- `../datasets/AGENTS.md`
- `../docs/data_lifecycle.md`
- `../docs/storage_layout.md`
- `../docs/data_dictionary.md`

## Source Contracts

### everef.net

- Market history lives at `data.everef.net/market-history/`.
- Market order snapshots live at `data.everef.net/market-orders/`.
- Market history archives are daily CSVs with ESI market history schema.
- Market order snapshots are full order book compressed CSVs with headers, roughly
  twice per hour.
- Archives may be updated in place; ingestion should use source metadata such as
  `totals.json` to detect changes and republish affected partitions.

### EVE ESI API

- dlt ESI source not yet implemented. Future work.
- Current focus: everef.net bulk archives through existing custom ingestion.
- Market history endpoint: `GET /markets/{region_id}/history/?type_id={type_id}`.
- Market orders endpoint: `GET /markets/{region_id}/orders/`.
- Market endpoints require no auth.
- Respect global 300 requests/minute limit.
- Respect `Expires` headers.
- Too many errors can trigger temporary bans.
- Treat market history `average` as VWAP.

## ESI Market History Shape

```json
{
  "average": 5.25,
  "date": "2015-05-01",
  "highest": 5.27,
  "lowest": 5.11,
  "order_count": 2267,
  "volume": 16276782035
}
```

## Ingestion Rules

- Python + dlt for source-specific extraction and publication.
- Publish through DuckLake table commits or merge/delete semantics.
- Preserve single-writer publication for the actual DuckLake mutation domain being
  changed, not just for a semantic dataset label.
- Distinguish snapshot datasets from authoritative datasets.
- Snapshot datasets publish observed states from discrete source snapshots; rows absent
  from a later snapshot are not implied deletions of earlier published snapshots.
- Authoritative datasets publish the latest accepted truth for an explicit source scope,
  such as a source date or a full reference extract; the publication scope must stay
  explicit in contracts and logs.
- When adding a new source or writer, declare all of the following up front in code and
  docs: semantic publication scope, physical raw/provenance tables mutated, writer
  idempotency mode, and the advisory lock domain(s) that serialize those mutations.
- Do not call `DuckLakeWriter.write()` or `DuckLakeWriter.upsert_source_object()` without
  a valid `DuckLakeLockToken` covering the target raw/provenance table domain.
- When adding a publisher, declare physical data tables, provenance tables, writer mode,
  semantic publication scope, and derived lock domains together.
- Choose writer behavior from dataset semantics, not from a generic key list alone.
- Current ingestion semantics:
  - `market_orders` and `fuzzwork_orders` are snapshot-oriented and use idempotent
    insert-missing-key semantics.
  - `market_history` is source-date-authoritative and currently uses
    assert-partition-coverage plus insert-missing semantics for each source date.
  - `references` ingests the latest full extracts and uses full-table replacement
    semantics per published reference table.
  - Raw-file provenance is dataset-scoped via `raw_market_history_objects`,
    `raw_market_orders_objects`, `raw_fuzzwork_orders_objects`, and
    `raw_reference_objects`; do not reuse the retired shared `raw_source_objects`
    contract.
- Maintenance or bootstrap work that mutates shared DuckLake metadata/table state must
  not overlap normal writers for the same lock domain set.
- Maintenance semantics are affected-domain based: acquire `ducklake:maintenance` plus
  affected raw/support domains. `ducklake:maintenance` alone is not a global pause.
- Raw bootstrap must acquire `ducklake:migration` plus every raw/support domain it may
  create or alter.
- Primary dev/execution path is `infra/local/compose.yml` Docker Compose stack.
  Direct `uv run` on host is deprecated.
- Use local SQLite DuckLake catalogs only for local development and smoke tests.
- Use PostgreSQL DuckLake catalogs for mounted/shared DuckLake storage in Docker
  Compose and Airflow runs.
- Do not write durable shared `.duckdb` files.
- Keep DuckDB scratch databases local or transient only.
- Update dataset contracts and docs when source semantics change.
