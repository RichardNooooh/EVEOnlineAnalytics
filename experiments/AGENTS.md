# experiments/AGENTS.md

Read this when changing validation experiments, evidence samples, notebooks, or local
research artifacts.

## Read First

- `../AGENTS.md`
- `../docs/AGENTS.md`
- `../datasets/AGENTS.md`

## Experiment Rules

- Experiments may provide evidence for data semantics, architecture choices, or model
  behavior.
- Keep durable project contracts in `../docs/` and `../datasets/`; experiments are
  supporting evidence, not source of truth by themselves.
- If an experiment validates a schema or semantic quirk, link it from relevant docs or
  contracts.
- Do not introduce durable shared `.duckdb` files here.

## Current Evidence

- `esi-average-field-validation/` is primary local evidence that ESI market history
  `average` should be treated as VWAP despite in-game median labeling.
