"""Bounded sktime/skchange PELT benchmark with ignored local runtime artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import statistics
import time
from datetime import UTC, date, datetime
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE.parent / "02_detection_method_exploration.ipynb"
RUNTIME_ROOT = HERE.parent / ".local" / "pelt-library-benchmark"
OUTPUT_DIR = RUNTIME_ROOT / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
np: Any
pl: Any
ChangePELT: Any
TimePELT: Any
COSTS: dict[str, dict[str, Any]] = {}
MIN_SEGMENT = 14
MULTIPLIERS = (0.5, 1.0, 2.0)
records: list[dict[str, Any]] = []
checks: list[dict[str, Any]] = []


def _load_backends():
    # Configure caches and parse --help before importing optional dependencies.
    global np, pl, ChangePELT, TimePELT, COSTS
    import numpy as np
    import polars as pl
    from skchange.detectors import PELT as ChangePELT
    from skchange.interval_scorers import L1Cost as ChangeL1
    from skchange.interval_scorers import L2Cost as ChangeL2
    from sktime.detection.costs import L1Cost as TimeL1
    from sktime.detection.costs import L2Cost as TimeL2
    from sktime.detection.pelt import PELT as TimePELT

    COSTS = {"L1": {"sktime": TimeL1, "skchange": ChangeL1}, "L2": {"sktime": TimeL2, "skchange": ChangeL2}}


def predict(backend, cost_name, x, penalty):
    cost = COSTS[cost_name][backend]()
    if backend == "sktime":
        detector = TimePELT(
            cost=cost,
            penalty=penalty,
            min_segment_length=MIN_SEGMENT,
            step_size=1,
            prune=True,
            split_cost=0.0,
            pruning_margin=0.0,
        )
        positions = detector.fit_predict(x)["ilocs"].to_numpy(dtype=int)
    else:
        detector = ChangePELT(
            cost=cost,
            penalty=penalty,
            penalty_scale=1.0,
            min_segment_length=MIN_SEGMENT,
            step_size=1,
            prune=True,
            split_cost=0.0,
            pruning_margin=0.0,
        )
        positions = detector.fit(x).predict(x)
        assert detector.penalty_ == penalty
    return np.asarray(positions, dtype=int)


def segment_cost(values, cost_name):
    center = np.median(values) if cost_name == "L1" else values.mean()
    differences = values - center
    return float(np.abs(differences).sum() if cost_name == "L1" else np.square(differences).sum())


def objective(x, positions, penalty, cost_name):
    edges = np.r_[0, positions, len(x)]
    assert np.all(np.diff(edges) >= MIN_SEGMENT), (positions, len(x))
    return sum(segment_cost(x[start:end, 0], cost_name) for start, end in pairwise(edges)) + penalty * len(positions)


def save_progress():
    (OUTPUT_DIR / "results.json").write_text(json.dumps({"records": records, "checks": checks}, indent=2) + "\n")


def timed_fit(case, backend, cost_name, multiplier, phase, repeat):
    x = case["x"]
    # Explicit numeric penalty, preserving the notebook's formula for L1/L2.
    penalty = float(multiplier * 2 * np.log(len(x)))
    start = time.perf_counter()
    positions = predict(backend, cost_name, x, penalty)
    elapsed = time.perf_counter() - start
    record = {
        "case": case["name"],
        "feature": case["feature"],
        "n": len(x),
        "backend": backend,
        "cost": cost_name,
        "multiplier": multiplier,
        "penalty": penalty,
        "phase": phase,
        "repeat": repeat,
        "seconds": elapsed,
        "positions": positions.tolist(),
        "dates": [str(case["dates"][position])[:10] for position in positions],
        "objective": objective(x, positions, penalty, cost_name),
    }
    records.append(record)
    save_progress()
    print(
        f"{phase:5} {case['name']:25} {cost_name} x{multiplier:<3g} {backend:8} "
        f"{elapsed:9.4f}s boundaries={len(positions)}",
        flush=True,
    )
    return record


def compare(first, second, scope):
    same_objective = bool(np.isclose(first["objective"], second["objective"], rtol=1e-9, atol=1e-8))
    check = {
        "scope": scope,
        "same_positions": first["positions"] == second["positions"],
        "same_objective": same_objective,
        "objective_difference": second["objective"] - first["objective"],
    }
    checks.append(check)
    save_progress()
    # Different tied optimal partitions should be reported, not silently rejected.
    assert same_objective, check
    return check


def independent_optimum(x, penalty, cost_name):
    optimum = np.full(len(x) + 1, np.inf)
    optimum[0] = -penalty
    for end in range(MIN_SEGMENT, len(x) + 1):
        values = [
            optimum[start] + segment_cost(x[start:end, 0], cost_name) + penalty
            for start in range(end - MIN_SEGMENT + 1)
            if np.isfinite(optimum[start])
        ]
        optimum[end] = min(values)
    return float(optimum[-1])


def validate_costs_and_optima(cases):
    rng = np.random.default_rng(13)
    for case in cases:
        x = case["x"]
        starts = rng.integers(0, len(x) - MIN_SEGMENT + 1, size=80)
        ends = np.array([rng.integers(start + MIN_SEGMENT, len(x) + 1) for start in starts])
        cuts = np.vstack((np.column_stack((starts, ends)), [[0, len(x)]]))
        for cost_name in COSTS:
            old_cost = COSTS[cost_name]["sktime"]()
            new_cost = COSTS[cost_name]["skchange"]().fit(x)
            old_values = old_cost.evaluate(x, cuts).ravel()
            new_values = new_cost.evaluate(new_cost.precompute(x), cuts).ravel()
            reference = np.array([segment_cost(x[start:end, 0], cost_name) for start, end in cuts])
            assert np.allclose(old_values, reference, rtol=1e-9, atol=1e-8)
            assert np.allclose(new_values, reference, rtol=1e-9, atol=1e-8)
            checks.append(
                {
                    "scope": f"interval costs/{case['name']}/{cost_name}",
                    "intervals": len(cuts),
                    "reference_parity": True,
                    "max_backend_difference": float(np.max(np.abs(old_values - new_values))),
                }
            )

    synthetic = {
        "minimum_two_segments": np.repeat([0.0, 2.0], 14),
        "level_step": np.repeat([0.0, 2.0], 45) + rng.normal(0, 0.02, 90),
        "flat_ties": np.zeros(56),
        "spike_and_reversal": np.r_[np.zeros(30), 4.0, np.zeros(59)] + rng.normal(0, 0.02, 90),
    }
    for name, values in synthetic.items():
        x = np.ascontiguousarray(values.reshape(-1, 1))
        for cost_name in COSTS:
            for multiplier in MULTIPLIERS:
                penalty = float(multiplier * 2 * np.log(len(x)))
                expected = independent_optimum(x, penalty, cost_name)
                positions = {}
                for backend in ("sktime", "skchange"):
                    positions[backend] = predict(backend, cost_name, x, penalty)
                    actual = objective(x, positions[backend], penalty, cost_name)
                    assert np.isclose(actual, expected, rtol=1e-9, atol=1e-8), (
                        name,
                        cost_name,
                        backend,
                        actual,
                        expected,
                    )
                checks.append(
                    {
                        "scope": f"oracle/{name}/{cost_name}/x{multiplier}",
                        "optimal_objective": expected,
                        "oracle_parity": True,
                        "same_positions": np.array_equal(positions["sktime"], positions["skchange"]),
                    }
                )
    save_progress()
    print(
        "PASS: interval costs, minimum lengths, boundary conventions, and independent exact-partition oracle.",
        flush=True,
    )


def prepare_cases(inputs=None):
    cases: list[dict[str, Any]] = []
    if inputs is not None:
        # Replay measured inputs without querying the local analytical database.
        provenance = json.loads(inputs.with_name("metadata.json").read_text())
        if hashlib.sha256(inputs.read_bytes()).hexdigest() != provenance["inputs_sha256"]:
            raise ValueError("Frozen inputs do not match their recorded checksum.")
        with np.load(inputs, allow_pickle=False) as frozen:
            for description in provenance["cases"]:
                name = description["name"]
                cases.append(
                    {key: description[key] for key in ("name", "feature", "mean", "std")}
                    | {"x": np.ascontiguousarray(frozen[f"{name}_x"]), "dates": frozen[f"{name}_dates"]}
                )
        input_source = str(inputs)
    else:
        raw = NOTEBOOK.read_bytes()
        notebook = json.loads(raw)
        namespace: dict[str, Any] = {
            "np": np,
            "pl": pl,
            "HISTORY_START": date(2022, 6, 1),
            "HISTORY_END": date(2026, 9, 1),
        }
        from transform.notebook_access import open_analysis_connection

        namespace["open_analysis_connection"] = open_analysis_connection
        cells = {cell["id"]: cell for cell in notebook["cells"]}
        # Stable cell IDs allow insertion/reordering of unrelated notebook cells.
        # The minimal namespace avoids loading notebook-only UI/profiling packages.
        for cell_id in ("input-sql", "input-calendar-features-slot", "6bffe3be", "de32960e", "f410c22c", "36ebf1a9"):
            exec(compile("".join(cells[cell_id]["source"]), f"notebook cell {cell_id}", "exec"), namespace)
        features = namespace["features"]
        rows = namespace["_prepare_pelt_rows"](features.filter(pl.col("type_id") == 34))
        runs = list(namespace["_iter_pelt_runs"](rows))
        activity = next(
            run
            for run in runs
            if run.get_column("feature")[0] == "log_volume" and run.get_column("feature_value").is_not_null().all()
        )
        prices = sorted(
            [
                run
                for run in runs
                if run.get_column("feature")[0] == "log_vwap"
                and run.get_column("feature_value").is_not_null().all()
                and run.height >= 28
            ],
            key=lambda run: run.height,
        )
        selections = [
            ("tritanium_activity_700", activity.slice(0, 700)),
            ("tritanium_activity_full", activity),
            ("tritanium_price_first", prices[0]),
            ("tritanium_price_long", prices[-1]),
        ]
        for name, run in selections:
            values = run.get_column("feature_value").to_numpy().astype(float, copy=False)
            mean, std = float(values.mean()), float(values.std(ddof=1))
            assert len(values) >= 28 and std > 1e-12
            dates = np.asarray(run.get_column("market_date").to_numpy(), dtype="datetime64[D]")
            assert np.all(np.diff(dates) == np.timedelta64(1, "D"))
            x = np.ascontiguousarray(((values - mean) / std).reshape(-1, 1))
            cases.append(
                {
                    "name": name,
                    "feature": run.get_column("feature")[0],
                    "x": x,
                    "dates": dates,
                    "mean": mean,
                    "std": std,
                }
            )
        provenance = {
            "notebook_path": str(NOTEBOOK.relative_to(HERE.parents[1])),
            "notebook_sha256": hashlib.sha256(raw).hexdigest(),
            "panel_rows": features.height,
            "panel_items": features.get_column("type_id").n_unique(),
        }
        input_source = "read-only notebook input cells"
    for case in cases:
        assert case["x"].shape == (len(case["dates"]), 1)
        assert len(case["x"]) >= 28 and np.isfinite(case["x"]).all()
        assert np.all(np.diff(case["dates"]) == np.timedelta64(1, "D"))
    np.savez_compressed(
        OUTPUT_DIR / "inputs.npz",
        **{f"{case['name']}_{field}": case[field] for case in cases for field in ("x", "dates")},
    )
    metadata = {
        "python": platform.python_version(),
        "packages": {
            name: version(name)
            for name in (
                "sktime",
                "skchange",
                "numpy",
                "polars",
                "pandas",
                "numba",
                "llvmlite",
                "scikit-learn",
                "duckdb",
            )
        },
        "input_source": input_source,
        "notebook_path": provenance["notebook_path"],
        "notebook_sha256": provenance["notebook_sha256"],
        "panel_rows": provenance["panel_rows"],
        "panel_items": provenance["panel_items"],
        "minimum_segment_length": MIN_SEGMENT,
        "step_size": 1,
        "ddof": 1,
        "penalty_formula": "multiplier * 2 * log(n)",
        "prune": True,
        "inputs_sha256": hashlib.sha256((OUTPUT_DIR / "inputs.npz").read_bytes()).hexdigest(),
        "cases": [
            {key: value for key, value in case.items() if key not in ("x", "dates")}
            | {"n": len(case["x"]), "start": str(case["dates"][0]), "end": str(case["dates"][-1])}
            for case in cases
        ],
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return cases


def write_summary(repeats):
    keys = sorted(
        {(record["case"], record["cost"], record["multiplier"]) for record in records if record["phase"] == "warm"}
    )
    summary = []
    for case, cost, multiplier in keys:
        selected = [
            record
            for record in records
            if record["case"] == case
            and record["cost"] == cost
            and record["multiplier"] == multiplier
            and record["phase"] == "warm"
        ]
        medians = {
            backend: statistics.median(record["seconds"] for record in selected if record["backend"] == backend)
            for backend in ("sktime", "skchange")
        }
        first = next(record for record in selected if record["backend"] == "sktime")
        second = next(record for record in selected if record["backend"] == "skchange")
        summary.append(
            {
                "case": case,
                "n": first["n"],
                "cost": cost,
                "multiplier": multiplier,
                "sktime_seconds": medians["sktime"],
                "skchange_seconds": medians["skchange"],
                "speedup": medians["sktime"] / medians["skchange"],
                "boundaries": len(first["positions"]),
                "same_positions": first["positions"] == second["positions"],
            }
        )
    with (OUTPUT_DIR / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "case",
                "n",
                "cost",
                "multiplier",
                "sktime_seconds",
                "skchange_seconds",
                "speedup",
                "boundaries",
                "same_positions",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(summary)
    lines = [
        "# PELT library benchmark",
        "",
        "Generated inputs and artifacts are local experiment outputs. No notebook, project dependency, or dataset publication was changed.",
        "",
        "## Method",
        "",
        f"- sktime {version('sktime')} versus skchange {version('skchange')}; {repeats} warm repetitions per configuration with randomized backend order.",
        "- Both use the same standardized float64 daily arrays, explicit numeric penalties, minimum segment length 14, step size 1, and pruning enabled.",
        "- Timings include detector construction, fit, and predict; exclude imports, input extraction/scaling, and result checks.",
        "- First invocation per backend/cost is separate from warm timings. L2 can reuse shared kernels compiled by L1. A fresh run-specific Numba cache was used.",
        f"- Both backends use the same runtime with Numba {version('numba')}. Full runtime versions are recorded in metadata.json.",
        "- Four cases come from one representative item (Tritanium). This is not a full-panel timing estimate.",
        "",
        "## First-invocation timings",
        "",
        "| Cost | Backend | Seconds |",
        "| --- | --- | ---: |",
    ]
    for record in records:
        if record["phase"] == "cold":
            lines.append(f"| {record['cost']} | {record['backend']} | {record['seconds']:.4f} |")
    lines += [
        "",
        "## Warm median timings",
        "",
        "| Case | n | Cost | Penalty multiplier | sktime seconds | skchange seconds | Speedup | Boundaries | Same positions |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary:
        lines.append(
            f"| {row['case']} | {row['n']} | {row['cost']} | {row['multiplier']:g} | {row['sktime_seconds']:.4f} | {row['skchange_seconds']:.4f} | {row['speedup']:.2f}x | {row['boundaries']} | {row['same_positions']} |"
        )
    lines += [
        "",
        "## Validation",
        "",
        "- Both backends agree with direct NumPy interval costs on 81 intervals per case/cost.",
        "- Both agree with an independent exact dynamic-programming oracle on minimum-length, level-step, flat/tied, and spike/reversal examples, across both costs and all three penalties.",
        f"- {sum(check.get('same_positions', True) is False for check in checks)} boundary-position mismatches across recorded checks. Objective tolerance: rtol=1e-9, atol=1e-8.",
        "- Every fitted segment satisfies the minimum length; terminal positions and run starts are not returned as boundaries.",
        "",
        "Raw repetitions, boundary dates, objectives, metadata, and frozen benchmark arrays are in `results.json`, `metadata.json`, and `inputs.npz`.",
    ]
    (OUTPUT_DIR / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    global OUTPUT_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warm-repeats", type=int, default=2)
    parser.add_argument(
        "--inputs", type=Path, help="Replay inputs.npz with adjacent metadata.json; otherwise query local data."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Run artifacts; defaults to a new directory under experiments/.local/.",
    )
    args = parser.parse_args()
    if args.warm_repeats < 1:
        parser.error("--warm-repeats must be at least 1")
    OUTPUT_DIR = args.output_dir.expanduser().resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(OUTPUT_DIR / "numba-cache"))
    os.environ.setdefault("MPLCONFIGDIR", str(RUNTIME_ROOT / "matplotlib-cache"))
    os.environ.setdefault("XDG_CACHE_HOME", str(RUNTIME_ROOT / "cache"))
    cache = Path(os.environ["NUMBA_CACHE_DIR"])
    existing = list(cache.rglob("*.nbc")) if cache.exists() else []
    assert not existing, "Cold measurement requires a new NUMBA_CACHE_DIR."
    _load_backends()
    cases = prepare_cases(args.inputs.expanduser().resolve() if args.inputs else None)
    print("Cases:", [(case["name"], len(case["x"])) for case in cases], flush=True)

    # Capture first invocation before cost checks/oracles can compile the kernels.
    for cost in COSTS:
        cold = [timed_fit(cases[0], backend, cost, 0.5, "cold", 0) for backend in ("sktime", "skchange")]
        compare(cold[0], cold[1], f"cold/{cost}")

    validate_costs_and_optima(cases)
    order = random.Random(42)
    for case in cases:
        for cost in COSTS:
            for multiplier in MULTIPLIERS:
                previous = {}
                for repeat in range(1, args.warm_repeats + 1):
                    backends = ["sktime", "skchange"]
                    order.shuffle(backends)
                    fitted = {
                        backend: timed_fit(case, backend, cost, multiplier, "warm", repeat) for backend in backends
                    }
                    compare(
                        fitted["sktime"], fitted["skchange"], f"warm/{case['name']}/{cost}/x{multiplier}/repeat{repeat}"
                    )
                    for backend, result in fitted.items():
                        if backend in previous:
                            assert previous[backend]["positions"] == result["positions"], "Non-deterministic positions"
                        previous[backend] = result
    write_summary(args.warm_repeats)
    print(f"PASS: benchmark and parity checks. Report: {OUTPUT_DIR / 'REPORT.md'}", flush=True)


if __name__ == "__main__":
    main()
