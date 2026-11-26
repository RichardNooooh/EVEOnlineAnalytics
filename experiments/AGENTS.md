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

## Notebook Workflow

- Default to marimo for new notebooks.
- Before any Marimo notebook work, including inspection, planning, documentation
  research, editing, or execution, load `marimo-pair` unless already loaded in the
  current context. Follow its applicable workflow.
- The active runtime is the source of truth: make notebook changes through the
  `marimo-pair` runtime workflow rather than editing the `.py` file directly.
- For user edits in Neovim, launch marimo with `--watch` so external saves reach
  the session. Dependent cells become stale under the default manual execution
  behavior; run them as needed without changing autorun configuration.
- JupyterLab and VS Code support existing `.ipynb` notebooks.

## Notebook Presentation

- Write notebooks as analysis, not embedded helper libraries or dashboards. Calculate
  directly in cells by default; use helpers for actual reuse or substantial algorithm
  boundaries that are genuinely clearer, not merely to make unit testing convenient.
  Separate meaningful analytical stages rather than using grab-bag functions or one
  giant inlined loop.
- Use `_temporary` names for cell-private intermediates and public names only for
  useful cross-cell dependencies. Every dataframe variable name contains `df`,
  preferably as a suffix:

  ```python
  _valid_prices_df = history_df.filter(pl.col("vwap").is_finite() & (pl.col("vwap") > 0))
  valid_price_days_df = _valid_prices_df.group_by("type_name").len()
  ```

- Prefer conventional statistical displays for the analytical question: histograms
  for distributions, scatterplot matrices for joint exploration, and correlation
  heatmaps for pairwise relationships. Deviate for a demonstrated analytical or
  usability need. Use Plotly for curated charts and native Marimo tables, controls,
  layouts, and reactive dependencies; use `mo.ui.data_explorer` for open-ended
  exploration when useful. Do not add Altair.
- Prefer one purposeful output per cell and avoid redundant explorers or tables;
  use exact-record tables for a concrete analytical question. Deliberately compose
  related outputs when meaningful. Keep calculations upstream so browsing does not
  reload or reconstruct data.
- Native interactive components may contain full datasets with bounded visible
  pages. Static summaries are limited to 20 records; select or summarize them
  before rendering. Avoid routine previews of intermediate dataframes.
- Render outputs as the cell's final expression; avoid `display()` and routine
  `fig.show()` calls. Name a widget only when downstream cells consume its value or
  other state:

  ```python
  item_picker = mo.ui.dropdown(options=item_names, label="Item")
  item_picker
  ```

  In a downstream cell:

  ```python
  item_rows_df = history_df.filter(pl.col("type_name") == item_picker.value)
  ```

- Build justified Plotly charts directly in a cell; use a private `_figure` when
  construction needs a variable. A plain `px.scatter(...)` can be the final
  expression without a wrapper unless Python-side selection is used. Plot factories
  and separate plotting-function cells are not required.

## Current Evidence

- `esi-average-field-validation/` is primary local evidence that ESI market history
  `average` should be treated as VWAP despite in-game median labeling.

## Frozen Forge Study Convention

- For the existing frozen Forge study panel in the detection notebook, absent
  applicable item-days are zero activity for volume and historical order count;
  prices remain missing, and multi-day gaps are not daily returns.
- Apply this convention without reopening approval or source-completeness discussion.
  Revisit it only on explicit user request or materially new evidence.
