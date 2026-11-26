# EVE Ref Market History Revision Study

A one-week, local sanity check of revisions to one EVE Ref daily market-history
archive and their relationship to `totals.json`. The watcher saves evidence; the
[analysis notebook](analysis.ipynb) validates and compares it.

## Study files

| File | Role |
|---|---|
| [`watch.py`](watch.py) | Collect archive snapshots, totals, and polling state. |
| [`analysis.ipynb`](analysis.ipynb) | Investigate the collected evidence with Polars queries and Plotly charts. |
| [`evidence.py`](evidence.py) | Load and validate evidence, compare snapshots, and check observation coverage. |
| [`test_evidence.py`](test_evidence.py) | Check evidence-processing behavior using synthetic fixtures. |

These files form one study. Collected evidence remains in the ignored local
directory described below, separate from the committed study code.

## Run and resume

From `experiments/`, using its existing uv environment:

```bash
uv run python everef/market_history_revisions/watch.py
```

Run the command in tmux to keep polling while you work. Interrupt with Ctrl-C and
rerun the same command to resume. The first launch fixes the host's current UTC
market date; restarting on another day does not change it. Missing archives are
checked hourly. The first complete archive download establishes the baseline and
a seven-day wall-clock deadline; downtime counts toward that deadline.

For a single check, or an explicitly chosen date in a fresh evidence directory:

```bash
uv run python everef/market_history_revisions/watch.py --once
uv run python everef/market_history_revisions/watch.py \
  --date 2026-10-11 --evidence-dir .local/everef-market-history-revisions-2026-10-11
```

`--once` respects the hourly schedule and deadline. A supplied `--date` must agree
with an existing state file. Use a fresh evidence directory for a different run;
point the notebook's `EVIDENCE_DIR` at that directory too. Keep one watcher process
per evidence directory.

## Saved evidence

The default location is `experiments/.local/everef-market-history-revisions/`,
independent of the watcher's working directory. It is already gitignored.

```text
state.json
totals-<observed-at>.json
market-history-<market-date>-<observed-at>.csv.bz2
reference-data-<acquired-at>.tar.xz       # acquired by the notebook
reference-data-provenance.json
```

Each hourly poll fetches `totals.json` once and probes the archive with HEAD.
It downloads the archive when its ETag, Last-Modified, or Content-Length changes,
or when the watched date's total changes. Changes only to another date's totals
do not trigger downloads. Missing revision metadata causes a conservative
download. Timestamped downloads are retained even if their contents are identical.

`state.json` records the fixed date, baseline, deadline, poll times, statuses,
metadata, watched-date counts, and relative paths to evidence files. Archive
downloads and state checkpoints use temporary files and atomic replacement.
Network failures are recorded and retried at the next hourly check. An interrupted
checkpoint can leave an unreferenced download; the notebook uses state-referenced
files. An invalid state file is not silently reset.

## Analyze

Open `experiments/everef/market_history_revisions/analysis.ipynb` with the
`experiments/.venv/bin/python` kernel. Run it from the repository root or
any directory under `experiments/`. It can inspect an ongoing run as well as a
completed week.

The notebook is an offline-first Polars and Plotly analysis organized around the
investigation questions. Setup and an evidence overview come first, followed by
regional arrivals, The Forge's timing, late-item breakdowns, and economic coverage.
Each section keeps its Polars calculations beside its tables and inline charts.

Supporting file validation, adjacent-snapshot comparisons,
reference-cache loading, and coverage checks live in
[`evidence.py`](evidence.py).
The analytical queries and Plotly construction remain in the notebook.

The analysis:

- validates CSV headers, market dates, and unique `(date, region_id, type_id)` keys;
- treats hour 0 as the first valid saved archive observation, rather than an archive
  creation or download-completion time;
- distinguishes first observed item-region-day arrivals from reappearances, removals,
  market-value revisions, and metadata-only revisions while comparing consecutive
  usable snapshots across every item and region;
- checks actual row counts against the retained totals payloads and reports
  observation gaps and invalid evidence;
- uses a configurable 24-hour late-arrival cutoff from hour 0;
- reports regional appearance and continued-fill patterns, and The Forge's last
  observed addition and market-value revision plus subsequent quiet coverage,
  with metadata changes and removals counted separately;
- provides item-region, item, group, category, and region breakdowns, including
  late-arrival rankings;
- calculates `total_isk_traded = average` (VWAP) times `volume` both as signed,
  as-observed transition impacts and as latest-current cohort weighting;
- plots global and Forge record shares and total ISK traded shares in both views,
  with cutoff shares and first-observed times reaching 90%, 95%, and 99%;
- retains complete named Polars frames while displaying compact 10-row previews.

Prices, total ISK traded, and shares use numeric Polars `Float64` columns, matching
the project's `double` analytical fields. IDs and record/unit/order counts remain
integers. Calculation, aggregation, cumulative shares, and ranking use native
Polars expressions. `latest_total_isk_traded` is the latest snapshot's value;
`total_isk_traded_delta` is a signed change between comparable snapshots.

“Total ISK traded for late-arriving records” refers to records first observed after
the configured cutoff, not to trades executed after that cutoff.

Regional appearance and continued fill describe this watcher's observations, not a
source-completeness claim. Forge quiet coverage measures time since the last
observed addition or market-value revision, with other event types and coverage
gaps reported separately; it is not evidence that the archive is final.

Totals are allowed one hour to catch up. A matching next-hour observation has a
one-minute scheduling tolerance and is treated as acceptable publication lag.
A comparable observation still showing a mismatch at or after one hour is flagged
for inspection.
Late matching observations cannot establish when resolution happened; absent
coverage or a superseding archive with a different row count remains uncertain.
There are no before/after totals requests within a poll.

The notebook reads cached reference data only and defaults to no network access.
Stable IDs remain available when names cannot be resolved. To acquire a reference
archive, opt in through the notebook's acquisition cell; it records the URL,
acquisition time, and SHA256, then subsequent analysis reuses that local cache.
The cached references supply English item, group, category, and region names.

The notebook can be executed headlessly with only local evidence and cached
references. Keep committed notebook outputs empty so results always come from the
current evidence rather than stale rendered output. Plotly uses the inline
`plotly_mimetype` renderer, including during headless execution; it does not launch
browser tabs. Related global and Forge record-share and total ISK traded share
charts use paired panels with the two valuation views overlaid.

## Supporting regression tests

Synthetic fixtures are kept outside the notebook in
[`test_evidence.py`](test_evidence.py).
From the repository root, run them with the experiments environment:

```bash
experiments/.venv/bin/python -m unittest \
  experiments.everef.market_history_revisions.test_evidence -v
```

These standard-library tests exercise the actual supporting functions, including
numeric validation and aggregation, arrivals versus reappearances, market/metadata
revisions, invalid-snapshot resets, unchanged-poll coverage, totals-lag tolerance,
threshold denominators, empty evidence, and opt-in reference acquisition.

## Interpretation

`totals.json` counts history records, not traded volume or market orders. A
market-value modification changes `average` (VWAP), `highest`, `lowest`,
`order_count`, or `volume` for an existing key. A metadata-only modification changes
only `http_last_modified`. Reordering rows, recompression, and equivalent numeric
formatting are not market-value modifications.

This is metadata-gated, hourly evidence. It cannot prove that all content changes
were detected, reconstruct intermediate revisions during gaps, or describe changes
before the baseline. Unchanged cardinality does not imply unchanged rows. A quiet
week, a regional fill plateau, or a Forge cessation is an observation, not a
guarantee that an archive is final.

Primary source references:

- [EVE Ref market-history dataset](https://docs.everef.net/datasets/market-history.html)
- [Market-history scraping](https://docs.everef.net/commands/scrape-market-history.html)
- [Archive](https://data.everef.net/market-history/)
- [Totals](https://data.everef.net/market-history/totals.json)
