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

- Use Python + dlt for source-specific extraction and publication.
- Publish through DuckLake table commits or merge/delete semantics.
- Preserve single-writer publication for the dataset scope.
- Do not write durable shared `.duckdb` files.
- Keep DuckDB scratch databases local or transient only.
- Update dataset contracts and docs when source semantics change.
