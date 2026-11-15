"""Selection primitives for comparisons of run-specific behavior partitions.

Dates are inclusive calendar days. Callers supply full observation support, including
reference days and interpolation endpoints, and choose all comparison periods and
overlap requirements. These helpers do not fit models or compare group labels.
"""

from dataclasses import replace

import numpy as np
import pandas as pd


def _days(values, name):
    dates = pd.to_datetime(values, errors="raise")
    if dates.isna().any() or getattr(dates.dt, "tz", None) is not None:
        raise ValueError(f"{name} must contain non-null, timezone-naive calendar days")
    if (dates != dates.dt.normalize()).any():
        raise ValueError(f"{name} must contain calendar days without times")
    return dates


def _period(period, name):
    if len(period) != 2:
        raise ValueError(f"{name} must contain a start and end")
    dates = _days(pd.Series(list(period)), name)
    if dates.iloc[0] > dates.iloc[1]:
        raise ValueError(f"{name} start must not exceed end")
    return dates.iloc[0], dates.iloc[1]


def _intervals(frame, start, end):
    starts = _days(frame[start], start)
    ends = _days(frame[end], end)
    if (starts > ends).any():
        raise ValueError(f"{start} must not exceed {end}")
    return starts, ends


def _keys(frame, columns):
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("key columns must be nonempty and distinct")
    if frame[columns].isna().any().any():
        raise ValueError("keys must not contain nulls")
    if frame.duplicated(columns).any():
        raise ValueError("keys must be unique")


def calendar_masks(frame, *, training_period, heldout_period):
    """Return index-aligned masks for support wholly inside two disjoint periods.

    ``frame`` supplies inclusive ``support_start`` and ``support_end`` for each
    observation, across all markets. Periods are inclusive (start, end) pairs;
    their order is unrestricted, but they must not touch or overlap. Observations
    crossing either boundary are excluded, even if their episode lies inside it.
    """
    train_start, train_end = _period(training_period, "training_period")
    test_start, test_end = _period(heldout_period, "heldout_period")
    if train_start <= test_end and test_start <= train_end:
        raise ValueError("training and heldout periods must be disjoint")
    starts, ends = _intervals(frame, "support_start", "support_end")
    return (
        (starts >= train_start) & (ends <= train_end),
        (starts >= test_start) & (ends <= test_end),
    )


def match_episode_windows(left, right, *, key_columns, market_columns, min_overlap_days):
    """Return every qualifying same-market pair of inclusive episode windows.

    Inputs have unique ``key_columns``, shared ``market_columns``, and
    ``episode_start``/``episode_end`` calendar-day columns. The explicit positive
    integer ``min_overlap_days`` is a caller-selected matching criterion. Output
    contains prefixed keys, original window bounds, overlap bounds/duration, and
    the zero-based overlap offsets within each episode, preserving phase and
    many-to-many matches. Run labels are deliberately not compared.
    """
    if isinstance(min_overlap_days, bool) or not isinstance(min_overlap_days, int) or min_overlap_days < 1:
        raise ValueError("min_overlap_days must be a positive integer")
    if not market_columns or len(set(market_columns)) != len(market_columns):
        raise ValueError("market columns must be nonempty and distinct")
    for frame in (left, right):
        _keys(frame, key_columns)
        if frame[market_columns].isna().any().any():
            raise ValueError("market columns must not contain nulls")
        _intervals(frame, "episode_start", "episode_end")
    if set(market_columns) & {"episode_start", "episode_end"} or set(key_columns) & {"episode_start", "episode_end"}:
        raise ValueError("key and market columns cannot be episode bounds")
    columns = list(dict.fromkeys([*market_columns, *key_columns, "episode_start", "episode_end"]))

    def side(frame, prefix):
        result = frame[columns].copy()
        result["episode_start"], result["episode_end"] = _intervals(result, "episode_start", "episode_end")
        return result.rename(columns={c: f"{prefix}_{c}" for c in columns if c not in market_columns})

    pairs = side(left, "left").merge(side(right, "right"), on=market_columns, how="inner")
    pairs["overlap_start"] = pairs[["left_episode_start", "right_episode_start"]].max(axis=1)
    pairs["overlap_end"] = pairs[["left_episode_end", "right_episode_end"]].min(axis=1)
    pairs["overlap_days"] = (pairs.overlap_end - pairs.overlap_start).dt.days + 1
    pairs = pairs.loc[pairs.overlap_days >= min_overlap_days].copy()
    for prefix in ("left", "right"):
        pairs[f"{prefix}_overlap_start_offset"] = (pairs.overlap_start - pairs[f"{prefix}_episode_start"]).dt.days
        pairs[f"{prefix}_overlap_end_offset"] = (pairs.overlap_end - pairs[f"{prefix}_episode_start"]).dt.days
    sort_columns = [
        *market_columns,
        *[f"left_{c}" for c in key_columns if c not in market_columns],
        *[f"right_{c}" for c in key_columns if c not in market_columns],
    ]
    return pairs.sort_values(sort_columns, kind="stable").reset_index(drop=True)


def common_eligible_keys(populations, *, key_columns):
    """Return sorted common keys and per-treatment eligibility retention counts.

    ``populations`` maps treatment names to frames containing unique keys and a
    non-null boolean ``eligible`` column. The returned retention frame reports
    each treatment's total, eligible, common, and eligible-but-not-common counts;
    eligible keys are intersected, not labels or independently fitted populations.
    Callers remain responsible for holding support, split, seeds and unchanged
    preprocessing fixed after alignment.
    """
    if not populations:
        raise ValueError("at least one population is required")
    common = None
    counts = []
    for name, frame in populations.items():
        _keys(frame, key_columns)
        if frame.eligible.isna().any() or not pd.api.types.is_bool_dtype(frame.eligible):
            raise ValueError("eligible must be non-null boolean")
        eligible = frame.loc[frame.eligible, key_columns]
        common = (
            eligible.copy()
            if common is None
            else common.merge(eligible, on=key_columns, how="inner", validate="one_to_one")
        )
        counts.append((name, len(frame), len(eligible)))
    common = common.sort_values(key_columns, kind="stable").reset_index(drop=True)
    retention = pd.DataFrame(
        [(name, total, eligible, len(common), eligible - len(common)) for name, total, eligible in counts],
        columns=["treatment", "total", "eligible", "common", "eligible_not_common"],
    )
    return common, retention


def _calendar_selection(frame, training_period, heldout_period):
    train, heldout = calendar_masks(frame, training_period=training_period, heldout_period=heldout_period)
    return train.to_numpy(), heldout.to_numpy()


def _descriptor_transform(raw, batch):
    """Apply the retained descriptor preprocessing without fitting anything."""
    from .behavior_workbench import MAGNITUDES, RATIOS

    x = np.asarray(raw, dtype=float)
    transform = batch.transformation
    z = (x - transform["mean"]) / transform["scale"]
    magnitudes = [i for i, feature in enumerate(batch.features) if feature in MAGNITUDES]
    ratios = [i for i, feature in enumerate(batch.features) if feature in RATIOS]
    strength = transform["strength"]
    z[:, magnitudes] = strength * np.arcsinh(z[:, magnitudes] / strength)
    if transform["bound_ratios"]:
        if np.any(x[:, ratios] < 0):
            raise ValueError("Activity ratios must be nonnegative")
        z[:, ratios] = (x[:, ratios] - 1) / (x[:, ratios] + 1)
    return z


def _descriptor_transfer(batch, raw):
    """Infer each retained run on finite raw rows; never fit a model."""
    prepared = _descriptor_transform(raw, batch)
    results = {}
    for run_id, run in batch.runs.items():
        if run["status"] != "ok":
            results[run_id] = {"status": run["status"], "reason": run["reason"]}
            continue
        rep = batch.representations[run["representation_id"]]
        method = rep["params"]["method"]
        try:
            if method == "prepared":
                embedding = prepared
            elif method in ("pca", "umap"):
                embedding = rep["model"].transform(prepared)
            elif method == "ae":
                import torch

                with torch.no_grad():
                    embedding = rep["model"][:5](torch.tensor(prepared, dtype=torch.float32)).numpy()
            else:
                raise ValueError(f"unsupported representation: {method}")
            distances = run["model"].transform(embedding)
            assignments = np.argmin(distances, axis=1)
            results[run_id] = {
                "status": "ok",
                "assignments": assignments,
                "distances": distances,
                "assignment_distances": distances[np.arange(len(distances)), assignments],
            }
        except Exception as exc:
            results[run_id] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
    return results


def _validate_ae_support(frame, weeks, eligible, settings):
    # AE's internal early-stopping split uses a fixed week-based purge. Check its
    # actual full support, rather than assuming that purge covers caller inputs.
    if "ae" not in settings.methods or not settings.ae_enabled:
        return
    from .behavior_workbench import calendar_split

    train, validation = calendar_split(weeks[eligible])
    starts, ends = _intervals(frame.iloc[np.flatnonzero(eligible)], "support_start", "support_end")
    if ends.iloc[np.flatnonzero(train)].max() >= starts.iloc[np.flatnonzero(validation)].min():
        raise ValueError("AE internal calendar split overlaps full observation support")


def calendar_descriptors(
    frame, *, key_columns, features, week_column, profile_columns, training_period, heldout_period, settings, mode
):
    """Fit descriptor calendar transfer or independent rediscovery, explicitly.

    Frame rows contain unique keys, full inclusive support, focal week, active
    features and caller-selected original-unit profile columns. ``settings`` is an
    explicit workbench Settings shortlist. ``mode`` is ``transfer`` or
    ``rediscovery``. Returned period frames retain original values and support;
    coverage counts include nonfinite-feature exclusions. Transfer inference is
    keyed by training run ID, with distances in that run's native geometry.
    Rediscovery returns independently fitted batches without matching labels.
    """
    from .behavior_workbench import explore

    if mode not in ("transfer", "rediscovery"):
        raise ValueError("mode must be transfer or rediscovery")
    _keys(frame, key_columns)
    raw = frame[features].to_numpy(dtype=float)
    weeks = _days(frame[week_column], week_column).to_numpy(dtype="datetime64[D]")
    train, heldout = _calendar_selection(frame, training_period, heldout_period)
    eligible = np.isfinite(raw).all(axis=1)
    period_masks = {"training": train, "heldout": heldout}
    selected = {name: mask & eligible for name, mask in period_masks.items()}
    if not selected["training"].any() or not selected["heldout"].any():
        raise ValueError("both periods require eligible observations")
    for name in ("training", "heldout") if mode == "rediscovery" else ("training",):
        indices = np.flatnonzero(selected[name])
        _validate_ae_support(frame.iloc[indices], weeks[indices], np.ones(len(indices), dtype=bool), settings)

    def fit(mask, period):
        indices = np.flatnonzero(mask)
        return explore(
            list(frame.iloc[indices][key_columns].itertuples(index=False, name=None)),
            raw[indices],
            features,
            weeks[indices],
            settings,
            input_metadata={"calendar_period": tuple(period)},
        )

    batches = {"training": fit(selected["training"], training_period)}
    if mode == "rediscovery":
        batches["heldout"] = fit(selected["heldout"], heldout_period)
    columns = list(
        dict.fromkeys([*key_columns, week_column, "support_start", "support_end", *profile_columns, *features])
    )
    profiles = {name: frame.loc[mask, columns].reset_index(drop=True).copy() for name, mask in selected.items()}
    coverage = {
        name: {
            "within_period": int(mask.sum()),
            "eligible": int(selected[name].sum()),
            "ineligible": int((mask & ~eligible).sum()),
        }
        for name, mask in period_masks.items()
    }
    coverage["outside_periods"] = int((~(train | heldout)).sum())
    return {
        "mode": mode,
        "batches": batches,
        "profiles": profiles,
        "coverage": coverage,
        "transfer": _descriptor_transfer(batches["training"], raw[selected["heldout"]]) if mode == "transfer" else None,
    }


def _path_subset(paths, mask):
    """Create a fitting subset, fitting scales on its unscaled transformed paths."""
    transformed = np.asarray(paths.transformed, dtype=float)[mask].copy()
    if transformed.ndim != 3 or not len(transformed) or not np.isfinite(transformed).all():
        raise ValueError("period requires nonempty finite transformed paths")
    scales = transformed.std(axis=(0, 1))
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise ValueError("period channel scales must be positive and finite")
    keys = paths.keys.iloc[np.flatnonzero(mask)].reset_index(drop=True).copy()
    return replace(
        paths,
        keys=keys,
        transformed=transformed,
        tensor=transformed / scales,
        scales=scales,
        scale_fit_keys=keys.copy(),
        scale_source="training",
        pairwise_bytes=len(keys) ** 2 * np.dtype(np.float64).itemsize,
    )


def _path_transfer(batch, transformed):
    from .behavior_paths import dependent_dtw

    tensor = transformed / batch.transformation["scales"]
    results = {}
    for run_id, run in batch.runs.items():
        if run["status"] != "ok":
            results[run_id] = {"status": run["status"], "reason": run["reason"]}
            continue
        rep = batch.representations[run["representation_id"]]
        try:
            method = rep["params"]["method"]
            if method == "aligned":
                distances = run["model"].transform(tensor.reshape(len(tensor), -1))
            elif method == "dtw":
                distances = np.array(
                    [
                        [dependent_dtw(path, medoid, band=rep["params"]["band"]) for medoid in run["medoid_paths"]]
                        for path in tensor
                    ]
                )
            else:
                raise ValueError(f"unsupported path representation: {method}")
            assignments = np.argmin(distances, axis=1)
            results[run_id] = {
                "status": "ok",
                "assignments": assignments,
                "distances": distances,
                "assignment_distances": distances[np.arange(len(distances)), assignments],
            }
        except Exception as exc:
            results[run_id] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
    return results


def calendar_joint_paths(
    paths, *, training_period, heldout_period, settings, mode, include_dtw, dtw_band, medoid_max_iter
):
    """Fit calendar checks on selected joint paths, with period-only channel scales.

    Support is reconstructed from original daily rows, including interpolation
    endpoints. Input ``tensor`` and its scales are never used for fitting or
    inference; ``transformed`` is rescaled independently for each fitted period.
    Returns period batches, their scaled JointPaths, original-unit summary profiles,
    selected-key coverage and (only for transfer) training-run keyed inference.
    Coverage describes the selected eligible input paths, not rejected candidates.
    """
    from .behavior_paths import summarize_joint_paths
    from .behavior_workbench import explore_paths

    if mode not in ("transfer", "rediscovery"):
        raise ValueError("mode must be transfer or rediscovery")
    key_columns = paths.keys.columns.tolist()
    _keys(paths.keys, key_columns)
    if len(paths.transformed) != len(paths.keys):
        raise ValueError("transformed paths and keys must align")
    transformed = np.asarray(paths.transformed, dtype=float)
    if transformed.ndim != 3 or not np.isfinite(transformed).all():
        raise ValueError("selected transformed paths must be finite three-dimensional data")
    summaries = summarize_joint_paths(paths)
    _keys(summaries, key_columns)
    profiles = paths.keys.merge(summaries, on=key_columns, how="left", validate="one_to_one", sort=False)
    train, heldout = _calendar_selection(profiles, training_period, heldout_period)
    if not train.any() or not heldout.any():
        raise ValueError("both periods require selected eligible paths")
    selected = {"training": train, "heldout": heldout}
    period_paths = {"training": _path_subset(paths, train)}
    if mode == "rediscovery":
        period_paths["heldout"] = _path_subset(paths, heldout)
    batches = {
        name: explore_paths(
            subset,
            settings,
            include_dtw=include_dtw,
            dtw_band=dtw_band,
            medoid_max_iter=medoid_max_iter,
            input_metadata={"calendar_period": tuple(training_period if name == "training" else heldout_period)},
        )
        for name, subset in period_paths.items()
    }
    return {
        "mode": mode,
        "batches": batches,
        "paths": period_paths,
        "profiles": {name: profiles.loc[mask].reset_index(drop=True) for name, mask in selected.items()},
        "coverage": {
            "training": int(train.sum()),
            "heldout": int(heldout.sum()),
            "outside_periods": int((~(train | heldout)).sum()),
        },
        "transfer": _path_transfer(batches["training"], transformed[heldout]) if mode == "transfer" else None,
    }


def targeted_descriptors(
    baseline, treatments, *, key_columns, features, week_column, split_column, split_values, settings, seed_namespace
):
    """Fit explicit descriptor treatments on the same eligible training keys.

    ``baseline`` and each treatment frame have keys, boolean ``eligible``, full
    inclusive support, focal week, and their active feature values. Treatments map
    names to dicts with ``frame``, ``features``, and ``changed_features``. Features
    can be selected or supplied by the caller; additions and changed retained
    coordinates must be declared in changed_features. Undeclared shared values,
    support, weeks, and split assignments must match exactly on the common keys.

    Pass split_column=None and split_values=None for a full-population fit, or an
    explicit split column and (training_value, heldout_value). Split supports must
    be globally disjoint. Eligibility counts are returned separately; nonfinite
    active values are treated as ineligible. The caller must supply a fixed seed
    and a nonempty seed_namespace. Each treatment fits its changed coordinates;
    unchanged coordinates reuse the baseline's prepared values and statistics.
    Optional heldout inference uses each treatment's fixed fitted models. Targeted
    AE is unsupported because its internal validation preprocessing is separate.
    """
    from .behavior_workbench import explore

    if not treatments or "baseline" in treatments:
        raise ValueError("provide named treatments distinct from baseline")
    if settings.seed is None or not isinstance(seed_namespace, str) or not seed_namespace:
        raise ValueError("a fixed seed and nonempty seed_namespace are required")
    if "ae" in settings.methods and settings.ae_enabled:
        raise ValueError("targeted AE is unsupported: its internal split needs shared preprocessing")
    if (split_column is None) != (split_values is None):
        raise ValueError("split_column and split_values must both be supplied or both be None")
    if split_column is not None and (len(split_values) != 2 or split_values[0] == split_values[1]):
        raise ValueError("split_values must contain distinct training and heldout values")

    specs = {"baseline": {"frame": baseline, "features": features, "changed_features": ()}, **treatments}
    populations = {}
    for name, spec in specs.items():
        frame, active = spec["frame"], list(spec["features"])
        _keys(frame, key_columns)
        if not active or len(set(active)) != len(active):
            raise ValueError(f"{name}: features must be nonempty and distinct")
        if frame.eligible.isna().any() or not pd.api.types.is_bool_dtype(frame.eligible):
            raise ValueError(f"{name}: eligible must be non-null boolean")
        _intervals(frame, "support_start", "support_end")
        _days(frame[week_column], week_column)
        populations[name] = frame[key_columns].copy()
        populations[name]["eligible"] = frame.eligible.to_numpy() & np.isfinite(
            frame[active].to_numpy(dtype=float)
        ).all(axis=1)
    common, retention = common_eligible_keys(populations, key_columns=key_columns)
    if common.empty:
        raise ValueError("no common eligible keys")
    aligned = {
        name: common.merge(spec["frame"], on=key_columns, how="left", validate="one_to_one", sort=False)
        for name, spec in specs.items()
    }
    base = aligned["baseline"]
    reference_columns = ["support_start", "support_end", week_column]
    if split_column is not None:
        reference_columns.append(split_column)
    for name, spec in treatments.items():
        frame = aligned[name]
        for column in reference_columns:
            if not base[column].equals(frame[column]):
                raise ValueError(f"{name}: {column} differs on common keys")
        active = set(spec["features"])
        changed = set(spec["changed_features"])
        if not changed <= active or not (active - set(features)) <= changed:
            raise ValueError(f"{name}: changed_features must declare added active features")
        for column in (active & set(features)) - changed:
            if not np.array_equal(base[column].to_numpy(), frame[column].to_numpy()):
                raise ValueError(f"{name}: undeclared change to {column}")
    if split_column is None:
        train = np.ones(len(common), dtype=bool)
        heldout = np.zeros(len(common), dtype=bool)
    else:
        if base[split_column].isna().any() or not base[split_column].isin(split_values).all():
            raise ValueError("split must assign every common key to a supplied split value")
        train = base[split_column].eq(split_values[0]).to_numpy()
        heldout = base[split_column].eq(split_values[1]).to_numpy()
        if not train.any() or not heldout.any():
            raise ValueError("split requires training and heldout observations")
        starts, ends = _intervals(base, "support_start", "support_end")
        train_starts = starts[train].to_numpy()
        train_ends = ends[train].to_numpy()
        order = np.argsort(train_starts)
        positions = np.searchsorted(train_starts[order], ends[heldout].to_numpy(), side="right")
        max_ends = np.maximum.accumulate(train_ends[order])
        if np.any((positions > 0) & (max_ends[np.maximum(positions - 1, 0)] >= starts[heldout].to_numpy())):
            raise ValueError("training and heldout full supports overlap")

    weeks = _days(base[week_column], week_column).to_numpy(dtype="datetime64[D]")
    _validate_ae_support(base.iloc[np.flatnonzero(train)], weeks[train], np.ones(train.sum(), dtype=bool), settings)
    batches, inference = {}, {}
    for name, spec in specs.items():
        frame, active = aligned[name], list(spec["features"])
        raw = frame[active].to_numpy(dtype=float)
        shared = None
        if name != "baseline":
            original = batches["baseline"]
            unchanged = (set(active) & set(features)) - set(spec["changed_features"])
            shared = {
                feature: {
                    "prepared": original.prepared[:, original.features.index(feature)].copy(),
                    "mean": original.transformation["mean"][original.features.index(feature)],
                    "scale": original.transformation["scale"][original.features.index(feature)],
                }
                for feature in unchanged
            }
        batches[name] = explore(
            list(common.loc[train].itertuples(index=False, name=None)),
            raw[train],
            active,
            weeks[train],
            settings,
            seed_namespace=seed_namespace,
            shared_preprocessing=shared,
            input_metadata={
                "treatment": name,
                "changed_features": tuple(spec["changed_features"]),
                "support": frame.loc[train, ["support_start", "support_end"]].astype(str).values.tolist(),
            },
        )
        inference[name] = _descriptor_transfer(batches[name], raw[heldout]) if heldout.any() else None
    return {
        "keys": common,
        "retention": retention,
        "frames": aligned,
        "training_mask": train,
        "heldout_mask": heldout,
        "batches": batches,
        "heldout": inference,
        "seed_namespace": seed_namespace,
    }


def _joint_support_structure(paths, common, key_columns):
    """Canonicalize each common key's daily roles and interpolation dependencies."""
    columns = [*key_columns, "date", "role", "interpolated", "interpolation_left", "interpolation_right"]
    daily = common.merge(paths.daily[columns], on=key_columns, how="left", validate="one_to_many")
    daily["date"] = _days(daily["date"], "date")
    if daily.duplicated([*key_columns, "date"]).any():
        raise ValueError("daily support must have unique key-date rows")
    if daily["role"].isna().any() or not daily["role"].isin(["reference", "episode"]).all():
        raise ValueError("daily support requires reference or episode roles")
    if daily["interpolated"].isna().any() or not pd.api.types.is_bool_dtype(daily["interpolated"]):
        raise ValueError("daily interpolation flags must be non-null boolean")
    for column in ("interpolation_left", "interpolation_right"):
        daily[column] = pd.to_datetime(daily[column], errors="raise").where(daily["interpolated"])
        if daily.loc[daily["interpolated"], column].isna().any():
            raise ValueError("interpolated support requires both dependency endpoints")
    return daily.sort_values([*key_columns, "date"], kind="stable").reset_index(drop=True)


def targeted_joint_paths(
    baseline,
    treatments,
    *,
    split_column,
    split_values,
    settings,
    seed_namespace,
    include_dtw,
    dtw_band,
    medoid_max_iter,
):
    """Fit caller-declared joint-channel treatments on common selected paths.

    ``baseline`` is a mapping with ``paths`` (JointPaths) and ``split`` (keyed
    DataFrame). Treatments map names to mappings containing ``paths``, ``split``,
    ``channels`` (ordered retained channel names) and ``changed_channels``. A
    treatment may remove channels or change retained transformed channel values;
    unchanged values and transform definitions must match exactly on all common
    keys. No new channels are accepted. Candidate eligibility is upstream: the
    retention table describes selected eligible keys with finite active channels.

    Each split frame contains exactly its paths' keys and ``split_column``. Supply
    two explicit ``split_values`` for fitting and heldout inference, or set both
    split arguments and every split frame to None for a full-population fit.
    Full inclusive support is reconstructed, including interpolation endpoints;
    daily roles, dates and interpolation dependencies and split assignments must
    agree across common keys. Baseline scales are
    fitted only on common training paths, then reused for each retained channel in
    every treatment, including changed channels. Labels remain run-specific.
    Treatment declarations and seed namespace are returned separately; they do
    not enter observation metadata solely as fitting controls.
    """
    from .behavior_paths import JointPaths, summarize_joint_paths
    from .behavior_workbench import explore_paths

    if not treatments or "baseline" in treatments:
        raise ValueError("provide named treatments distinct from baseline")
    if settings.seed is None or not isinstance(seed_namespace, str) or not seed_namespace:
        raise ValueError("a fixed seed and nonempty seed_namespace are required")
    if (split_column is None) != (split_values is None):
        raise ValueError("split_column and split_values must both be supplied or both be None")
    if split_values is not None and (len(split_values) != 2 or split_values[0] == split_values[1]):
        raise ValueError("split_values must contain distinct training and heldout values")
    base_paths = baseline["paths"]
    if not isinstance(base_paths, JointPaths):
        raise TypeError("baseline paths must be JointPaths")
    key_columns = base_paths.keys.columns.tolist()
    base_channels = tuple(base_paths.channels)
    if not base_channels or len(set(base_channels)) != len(base_channels):
        raise ValueError("baseline channels must be nonempty and unique")
    specs = {"baseline": {**baseline, "channels": base_channels, "changed_channels": ()}, **treatments}
    populations, summaries, arrays, splits = {}, {}, {}, {}
    for name, spec in specs.items():
        paths = spec["paths"]
        if not isinstance(paths, JointPaths) or list(paths.keys.columns) != key_columns:
            raise ValueError(f"{name}: path key columns must match baseline")
        _keys(paths.keys, key_columns)
        channels = tuple(paths.channels)
        active = tuple(spec["channels"])
        changed = tuple(spec["changed_channels"])
        if not active or len(set(active)) != len(active) or len(set(channels)) != len(channels):
            raise ValueError(f"{name}: channels must be nonempty and unique")
        if not set(active) <= set(base_channels) or not set(active) <= set(channels):
            raise ValueError(f"{name}: active channels must exist in baseline and treatment")
        if len(set(changed)) != len(changed) or not set(changed) <= set(active):
            raise ValueError(f"{name}: changed_channels must be distinct retained channels")
        data = np.asarray(paths.transformed, dtype=float)
        if (
            data.ndim != 3
            or data.shape[0] != len(paths.keys)
            or data.shape[2] != len(channels)
            or len(paths.transforms) != len(channels)
        ):
            raise ValueError(f"{name}: transformed paths, keys and channel metadata must align")
        arrays[name] = data[:, :, [channels.index(c) for c in active]]
        populations[name] = paths.keys.copy()
        populations[name]["eligible"] = np.isfinite(arrays[name]).all(axis=(1, 2))
        summary = summarize_joint_paths(paths)
        _keys(summary, key_columns)
        summaries[name] = paths.keys.merge(summary, on=key_columns, how="left", validate="one_to_one", sort=False)
        _intervals(summaries[name], "support_start", "support_end")
        split = spec["split"]
        if split_column is None:
            if split is not None:
                raise ValueError(f"{name}: split must be None for a full-population fit")
        else:
            _keys(split, key_columns)
            if (
                len(split) != len(paths.keys)
                or not pd.MultiIndex.from_frame(paths.keys).isin(pd.MultiIndex.from_frame(split[key_columns])).all()
            ):
                raise ValueError(f"{name}: split keys must exactly match selected path keys")
            splits[name] = paths.keys.merge(
                split[[*key_columns, split_column]], on=key_columns, validate="one_to_one", sort=False
            )
            if splits[name][split_column].isna().any() or not splits[name][split_column].isin(split_values).all():
                raise ValueError(f"{name}: invalid split assignment")
    common, retention = common_eligible_keys(populations, key_columns=key_columns)
    if common.empty:
        raise ValueError("no common eligible keys")
    aligned_arrays, aligned_profiles, aligned_splits = {}, {}, {}
    for name, spec in specs.items():
        positions = pd.MultiIndex.from_frame(spec["paths"].keys).get_indexer(pd.MultiIndex.from_frame(common))
        aligned_arrays[name] = arrays[name][positions]
        aligned_profiles[name] = summaries[name].iloc[positions].reset_index(drop=True)
        if split_column is not None:
            aligned_splits[name] = splits[name].iloc[positions].reset_index(drop=True)
    base_profile = aligned_profiles["baseline"]
    base_support = _joint_support_structure(base_paths, common, key_columns)
    for name, spec in treatments.items():
        for col in ("support_start", "support_end"):
            if not base_profile[col].equals(aligned_profiles[name][col]):
                raise ValueError(f"{name}: {col} differs on common keys")
        if not base_support.equals(_joint_support_structure(spec["paths"], common, key_columns)):
            raise ValueError(f"{name}: daily support or interpolation dependencies differ on common keys")
        if split_column is not None and not aligned_splits["baseline"][split_column].equals(
            aligned_splits[name][split_column]
        ):
            raise ValueError(f"{name}: split differs on common keys")
        if aligned_arrays[name].shape[1] != aligned_arrays["baseline"].shape[1]:
            raise ValueError(f"{name}: path lengths differ")
        for index, channel in enumerate(spec["channels"]):
            if channel not in spec["changed_channels"]:
                base_index = base_channels.index(channel)
                current_index = tuple(spec["paths"].channels).index(channel)
                if spec["paths"].transforms[current_index] != base_paths.transforms[base_index] or not np.array_equal(
                    aligned_arrays[name][:, :, index], aligned_arrays["baseline"][:, :, base_index]
                ):
                    raise ValueError(f"{name}: undeclared change to {channel}")
    if split_column is None:
        train = np.ones(len(common), dtype=bool)
        heldout = np.zeros(len(common), dtype=bool)
    else:
        split = aligned_splits["baseline"][split_column]
        train, heldout = split.eq(split_values[0]).to_numpy(), split.eq(split_values[1]).to_numpy()
        if not train.any() or not heldout.any():
            raise ValueError("split requires training and heldout observations")
        starts, ends = _intervals(base_profile, "support_start", "support_end")
        train_starts, train_ends = starts[train].to_numpy(), ends[train].to_numpy()
        order = np.argsort(train_starts)
        positions = np.searchsorted(train_starts[order], ends[heldout].to_numpy(), side="right")
        max_ends = np.maximum.accumulate(train_ends[order])
        if np.any((positions > 0) & (max_ends[np.maximum(positions - 1, 0)] >= starts[heldout].to_numpy())):
            raise ValueError("training and heldout full supports overlap")
    scales = aligned_arrays["baseline"][train].std(axis=(0, 1))
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise ValueError("baseline training channel scales must be positive and finite")
    batches, fit_paths, inference = {}, {}, {}
    for name, spec in specs.items():
        source = spec["paths"]
        active = tuple(spec["channels"])
        channel_scales = scales[[base_channels.index(c) for c in active]]
        transformed = aligned_arrays[name][train].copy()
        fit_keys = common.loc[train].reset_index(drop=True).copy()
        subset = replace(
            source,
            keys=fit_keys,
            transformed=transformed,
            tensor=transformed / channel_scales,
            channels=active,
            transforms=tuple(source.transforms[tuple(source.channels).index(c)] for c in active),
            scales=channel_scales.copy(),
            scale_fit_keys=fit_keys.copy(),
            scale_source="training",
            pairwise_bytes=len(fit_keys) ** 2 * np.dtype(np.float64).itemsize,
        )
        fit_paths[name] = subset
        batches[name] = explore_paths(
            subset,
            settings,
            include_dtw=include_dtw,
            dtw_band=dtw_band,
            medoid_max_iter=medoid_max_iter,
            seed_namespace=seed_namespace,
            input_metadata={
                "support": aligned_profiles[name]
                .loc[train, ["support_start", "support_end"]]
                .astype(str)
                .values.tolist()
            },
        )
        inference[name] = _path_transfer(batches[name], aligned_arrays[name][heldout]) if heldout.any() else None
    return {
        "keys": common,
        "retention": retention,
        "profiles": aligned_profiles,
        "training_mask": train,
        "heldout_mask": heldout,
        "batches": batches,
        "paths": fit_paths,
        "heldout": inference,
        "seed_namespace": seed_namespace,
        "treatments": {
            name: {"channels": tuple(spec["channels"]), "changed_channels": tuple(spec["changed_channels"])}
            for name, spec in treatments.items()
        },
    }
