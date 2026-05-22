# docs/AGENTS.md

Read this when changing docs, ADRs, architecture contracts, or README-level project
positioning.

## Read First

- `../AGENTS.md`
- `architecture.md`
- `data_lifecycle.md`
- `storage_layout.md`
- `runtime_contract.md` when changing workload-to-platform runtime boundaries
- `data_dictionary.md` when changing dataset semantics
- `adr/` when changing durable architecture decisions

## Documentation Rules

- Prefer `docs/` first, then `README.md` only when user-facing overview changes.
- Keep project framed as virtual economy analytics, not gaming tooling.
- Preserve hard storage contract: DuckLake over Parquet files, PostgreSQL catalog for
  production-style deployments, DuckDB as local/transient compute only.
- Update ADRs before implementation when changing architecture decisions.
- Cross-link source-specific semantics from docs to relevant dataset and ingestion
  contracts.

## Key Semantics

- ESI market history `average` is treated as VWAP.
- The in-game client may label the corresponding value as `median`; project contracts
  should document API field semantics as VWAP.
- Primary local evidence for this quirk lives under
  `../experiments/esi-average-field-validation/`.

## Architecture Update Order

- Storage architecture: `architecture.md`, `storage_layout.md`, relevant ADRs.
- Dataset lifecycle: `data_lifecycle.md`, dataset contracts, manifests/examples.
- ML-facing semantics: `data_dictionary.md`, `model_card.md`, transform contracts.
