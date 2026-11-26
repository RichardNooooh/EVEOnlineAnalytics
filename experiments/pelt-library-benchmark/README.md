# PELT Library Benchmark

AI-assisted benchmarking.

Compare sktime 1.2.0 and skchange 0.18.0 on the detection notebook's L1/L2
segmentation settings. This is supporting performance/parity evidence, not a
dataset publication or a selected economic model.

## Why This Was Benchmarked

The user reported that one outer configuration of the detection notebook's
full grid took about 1.5 hours. That is an observed full-grid runtime, not a
benchmark measurement. A bounded profile of the same work found repeated
sktime L1 median calculations accounted for about 98% of the profiled time.

Research identified skchange as a compatible alternative, so this benchmark
changed the segmentation backend only. It preserves the standardized daily
inputs, explicit penalties, and the 14-day minimum-segment semantics. The
bounded measurements below establish parity and per-fit speedups; they do not
estimate or report the full-grid runtime. Together, they support selecting
skchange for this already accepted solution.

## Retained Evidence

[`evidence/REPORT.md`](evidence/REPORT.md) contains the original cold/warm
measurements. Across four Tritanium activity/price histories and three penalty
multipliers, skchange was 5.1–21.8× faster for warm L1 fits and 2.6–3.4× faster
for L2. All tested boundary positions and objective costs matched. These are
single-item results, not a full-panel runtime estimate.

The evidence directory also retains the timing CSV, raw repetitions/checks,
version/provenance metadata, and a small frozen standardized input sample.
The original measurement ran in a temporary isolated environment. Its metadata
retains the original notebook hash; that hash need not match a subsequently
edited notebook. That environment and its vendor overlay are historical
provenance, not the setup for new runs.

## Setup

New runs use the shared experiments environment. It declares
`skchange[numba]==0.18.0` and a compatible Numba version below 0.68 alongside
the existing benchmark dependencies. From `experiments/`, sync that environment:

```bash
uv sync
```

Every new run records its actual versions. The original isolated environment
used Numba 0.67.0 and NumPy 2.4.4; its recorded versions remain in
[`evidence/metadata.json`](evidence/metadata.json).

Run the benchmark commands below from the repository root.

## Replay the Frozen Inputs

This path requires no analytical database or live notebook execution:

```bash
PYTHONDONTWRITEBYTECODE=1 \
experiments/.venv/bin/python -B \
  experiments/pelt-library-benchmark/benchmark.py \
  --inputs experiments/pelt-library-benchmark/evidence/inputs.npz
```

The input checksum is checked against the adjacent `metadata.json`. The
default is two warm repetitions for each of four inputs, both L1/L2 costs,
and penalty multipliers `0.5`, `1`, and `2`. Expect several minutes because
the slow sktime baseline is intentionally included.

## Benchmark Current Local Inputs

Omit `--inputs` to execute the notebook's read-only input, calendar, feature,
and PELT-row preparation cells, resolved by cell ID. The runner supplies a
minimal Polars/NumPy namespace and does not load notebook-only viewer or
profiling packages. This requires the local dbt build and DuckLake access
described in the parent experiments README:

```bash
PYTHONDONTWRITEBYTECODE=1 \
experiments/.venv/bin/python -B \
  experiments/pelt-library-benchmark/benchmark.py
```

## Outputs and Timing Semantics

Each invocation writes to a new timestamped directory under ignored
`experiments/.local/pelt-library-benchmark/runs/`. Use `--output-dir` to select
another location and `--warm-repeats` to change the repetition count.
Retained evidence is not overwritten by default.

Each run gets a fresh Numba compilation cache. If `NUMBA_CACHE_DIR` is supplied
externally, it must be empty of compiled kernels for cold measurements. Other
generated caches also default to `experiments/.local/`.

First-call timing includes compilation or first-use overhead after imports;
L2 may reuse shared kernels compiled by L1. Warm timing includes detector
construction, fit, and predict. Imports, extraction/scaling, and result checks
are excluded. Backend order is randomized within warm repetitions.

Both backends receive the same float64 daily arrays, explicit numeric penalties,
minimum segment length 14, step size 1, and pruning enabled. Direct interval
costs and an independent exact-partitioning oracle check parity, minimum-length
behavior, and boundary conventions. New reports, CSVs, incremental results,
metadata, and frozen inputs are all written to the run directory.
