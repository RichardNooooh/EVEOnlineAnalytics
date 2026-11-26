# Experiments

Exploratory notebooks provide supporting evidence for analytical decisions. Durable
transformations belong in dbt after an experiment establishes a stable rule.

## Detection Performance Evidence

[`pelt-library-benchmark/`](pelt-library-benchmark/README.md) contains the
sktime/skchange L1/L2 benchmark runner and retained timing/parity evidence.
It can replay the frozen sample without a database or use the detection
notebook's current read-only inputs. New runs use dependencies declared in the
shared experiments environment; the original isolated overlay is retained only
as historical provenance. New outputs and caches live under `experiments/.local/`.

## EVE Ref Studies

Source exploration, ingestion prototypes, and archive-behavior studies live in
`everef/`. Notebook names describe their subject; they are not a chronological
sequence.

| Notebook | Purpose |
|---|---|
| [Endpoint exploration](everef/endpoint-exploration.ipynb) | Explore source datasets, schemas, and reference-data relationships. |
| [Market-history dlt prototype](everef/market-history-dlt.ipynb) | Explore source extraction and local DuckLake destination configuration. |
| [In-place archive updates](everef/market-history-inplace-update-exploration.ipynb) | Inspect archive metadata and publication behavior. |
| [Market-history revisions](everef/market_history_revisions/analysis.ipynb) | Compare retained archive snapshots and totals; see the [study files and watcher instructions](everef/market_history_revisions/README.md). |

Use the shared experiments environment for these notebooks. Run them from the
repository root or any directory under `experiments/`; local paths are resolved
from the repository root. Cached source files and revision evidence remain under
`experiments/.local/`. The dlt prototype's filesystem destination remains under
the repository-root `.local/notebook/data/bronze/`.

## Notebook Setup

New notebooks default to marimo and use the shared experiments environment.
From the repository root, sync dependencies and open a notebook:

```bash
uv sync --project experiments
mise run marimo:edit -- experiments/path/to/notebook.py
```

The `marimo:edit` task enables `--watch` to synchronize external saves from Neovim
with the session. Under
the default manual execution behavior, affected dependent cells become stale and
can be run when needed. Agents editing a live session use the `marimo-pair` workflow.

Existing `.ipynb` notebooks remain supported in JupyterLab and VS Code. Start
JupyterLab from the repository root with `mise run jupyter:lab`, or select
`experiments/.venv/bin/python` as the notebook kernel in VS Code.

The experiments project installs the local `transformation` package as an
editable dependency, so notebooks can use the shared read-only connection helper:

```python
from transform.notebook_access import open_analysis_connection

with open_analysis_connection() as connection:
    forge_history = connection.sql("""
        select *
        from main.int_forge_market_history
        limit 10
    """).pl()
```

Use Polars DataFrames (`pl.DataFrame`) for notebook data preparation and analysis;
the `.pl()` relation method keeps query results in that representation. For VS
Code notebooks, restart the kernel after syncing dependencies.

### Interactive Study Notebooks

- `market_analysis/01_eda_and_study_panel_selection.ipynb` has Plotly ranking and source-row
  presence charts. Its PyGWalker dataset selector includes the full pre-selection
  activity rankings, reference/product tables, selected panel, and history summaries.
- [Weekly item peer network](market_analysis/02_item_peer_network.py) tracks
  which of the 99 panel items repeatedly move to the same side of their other
  peers’ median weekly change. Play or scrub the timeline to follow links across
  weeks. Focus an item to see which neighbors it gained, lost, or retained;
  the timeline counts remain network-wide. Positions help track items and do
  not measure economic distance. Open the notebook with
  `mise run marimo:edit -- experiments/market_analysis/02_item_peer_network.py`.
- `market_analysis/03_detection_method_exploration.ipynb` has a Plotly signal
  explorer with method, feature, category, date, and item controls. Heatmap rows
  are ordered by category and type ID. Hover shows original scores and baseline
  diagnostics; color clipping does not change scores. Unscored observations
  remain distinct. The individual review plots can include retrospective PELT context.
- PyGWalker in the study-panel and detection notebooks launches only when **Launch PyGWalker** is pressed.
  Datasets are selectable, filters are optional, and there is no automatic
  sampling. Both notebooks explicitly use offline privacy mode and disable cloud
  computation. In the detection notebook, full-history MAD/Z-score tables and the
  comparison are separate from PELT boundaries, segments, and diagnostics;
  interval tables use overlapping-date filters.
- **Build ProfileReport** in the detection notebook generates a report for the
  selected item, dates, and features on demand. Reports display inline rather
  than being generated automatically for the whole panel.

The study-panel notebook uses `market_analysis/reference_data.py` for retained
archive loading and manufacturing records, `market_analysis/plotting/eda.py` for
figures, and `market_analysis/plotting/production_graph.py` for the interactive
production graph. The plotting functions accept analytical data and return figures
or self-contained HTML; the graph embeds its adjacent `production_graph.js`.
Repository-root discovery supports kernels started at the repository root,
`experiments/`, or `experiments/market_analysis/`.

Filtering, joins, and detector tables remain Polars. The installed PyGWalker
release needs a pandas conversion at its input boundary for compatibility with
Polars 2; profiling also needs pandas. Retain `pandas>=2.3,<3` for the accepted
profiler.

Kernel-side figure construction, controls, local explorer HTML, and profiling
rendering have been checked. Actual hover and button interaction in the VS Code
notebook frontend still require a manual check. Run cells in order to populate
the explorer datasets; the PELT grid is a separate, comparatively expensive cell.

Run the dbt transformation build before querying its local relations. Close notebook
connections before rebuilding; the context manager closes the connection after each
`with` block. The default dbt work database remains
`/tmp/eve_market_transform.duckdb`, so notebook code does not change between builds.

The helper reads local catalog settings from `infra/local/.env` and honors the dbt
environment variables when present. It attaches raw DuckLake read-only and does not
create a durable database under `experiments/`.
