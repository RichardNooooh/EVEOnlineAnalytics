# datasets/AGENTS.md

Read this when changing dataset contracts, schemas, reference datasets, examples, or
manifests.

## Read First

- `../AGENTS.md`
- `../docs/data_lifecycle.md`
- `../docs/storage_layout.md`
- `../docs/data_dictionary.md`
- `../ingestion/AGENTS.md` for source-specific ingestion behavior

## Dataset Rules

- DuckLake tables backed by Parquet files are the system of record.
- Contracts and manifests describe publication state, schema expectations, and reader
  assumptions.
- Dataset publication must preserve single-writer semantics for each publication
  scope.
- Reference datasets should map `type_id` to item names from the Static Data Export.

## Market Data Semantics

- The Forge primary region ID is `10000002`.
- Jita station ID is `30000142`.
- ESI market history `average` means VWAP for this project.
- Do not rename ESI `average` to median in contracts unless explicitly documenting
  source/client label differences.

## Common Changes

- New data source: update dataset contract, examples/manifests if useful,
  `../docs/data_dictionary.md`, and planned dbt staging source definitions.
- Schema meaning change: update contract, data dictionary, and any transform model that
  consumes the field.
- Publication layout change: update `../docs/storage_layout.md` and relevant ADRs
  before implementation.
