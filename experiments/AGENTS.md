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

## Notebook Presentation

- Target VSCode notebooks and JupyterLab as the execution environments.
- Produce at most one table or visual per code cell. Calculation-only cells need
  not produce output.
- Render tables and visuals using the cell's final expression, normally a single
  variable. Do not use `display()` or routine `fig.show()` calls. Configure notebook
  rendering in setup only if necessary.
- Prefer graphs and other visuals over tables. Include a table only when its exact
  values or records serve a specific analytical purpose.
- Each rendered table must contain at most 20 rows. Summarize or select relevant
  records before rendering; do not rely on display truncation.
- Keep each notebook to a few small tables. Do not add routine dataframe previews
  after intermediate calculations.

## Current Evidence

- `esi-average-field-validation/` is primary local evidence that ESI market history
  `average` should be treated as VWAP despite in-game median labeling.

## Frozen Forge Study Convention

- For the existing frozen Forge study panel in the detection notebook, absent
  applicable item-days are zero activity for volume and historical order count;
  prices remain missing, and multi-day gaps are not daily returns.
- Apply this convention without reopening approval or source-completeness discussion.
  Revisit it only on explicit user request or materially new evidence.
