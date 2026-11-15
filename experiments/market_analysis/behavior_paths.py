"""Reference-relative joint paths and dependent DTW, without storage or plotting.

Input is an already applicable, daily market panel. Missing calendar rows are an
error: in particular, upstream must distinguish absent-day zero activity from
observed null activity. Episode keys are market columns plus ``start``. The
selected tensor is shared by aligned and DTW comparisons; subset selection
happens before the pooled channel scales are fitted.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numba import njit


@dataclass
class JointPaths:
    """Prepared paths in selected-key order; candidates include rejected windows.

    ``daily`` retains every candidate's original and prepared daily observations,
    interpolation endpoints, and whether each row is reference or episode support.
    ``transformed`` and ``tensor`` have shape (selected episodes, days, 2), with
    price then activity. ``tensor`` is transformed divided by pooled channel scales.
    ``scale_fit_keys`` records the selected keys used to fit scales, or is None
    when scales are externally supplied or no fit was possible. ``scale_source``
    is ``selected``, ``training``, ``provided``, or ``unfitted``.
    ``origin_shift_days`` records the requested offset from the Sunday anchor.
    """

    candidates: pd.DataFrame
    keys: pd.DataFrame
    daily: pd.DataFrame
    transformed: np.ndarray
    tensor: np.ndarray
    scales: np.ndarray
    channels: tuple[str, str]
    transforms: tuple[str, str]
    subset_seed: int | None
    pairwise_bytes: int
    scale_fit_keys: pd.DataFrame | None = None
    scale_source: str = "unfitted"
    origin_shift_days: int = 0


def prepare_joint_paths(
    history: pd.DataFrame,
    *,
    market_columns: tuple[str, ...] = ("region_id", "type_id"),
    date_column: str = "date",
    price_column: str = "average",
    activity_column: str = "volume",
    observed_column: str | None = None,
    window: int = 14,
    stride: int = 7,
    reference_days: int = 14,
    min_price_reference: int = 10,
    subset_size: int | None = None,
    seed: int = 0,
    scale_fit_keys: pd.DataFrame | None = None,
    scales: np.ndarray | None = None,
    origin_shift_days: int = 0,
) -> JointPaths:
    """Build calendar-anchored episodes and retain candidate/support provenance.

    Prices are interpolated between finite observations across the entire market
    history, never extrapolated, including source-observed null prices. When
    ``observed_column`` is provided, its flag is retained as provenance. Null
    activity is never interpolated and makes the relevant support ineligible.
    Reference price uses *observed* positive finite
    VWAP, not interpolated VWAP. Reference activity requires all days finite and
    nonnegative. A zero pooled standard deviation is an error, not a hidden scale.
    Optional sampling round-robins seeded market/calendar-quarter strata, retaining
    exact keys; ``None`` keeps the full eligible population.
    If no episodes are eligible, return empty tensors and unfitted NaN scales
    unless scales were supplied; candidate and daily tables retain their columns.
    By default scales are fitted on all selected paths. Alternatively pass a
    nonempty DataFrame of unique selected eligible keys in ``scale_fit_keys``;
    only those paths fit the scales, which are applied to every selected path.
    Or pass previously fitted positive finite ``scales`` in channel order.
    These options are mutually exclusive. The caller must ensure matching channel
    and preparation definitions and leakage-safe full support for training keys.
    ``origin_shift_days`` offsets the first Sunday on or after each market's first
    date; equivalent offsets modulo ``stride`` yield the same calendar grid. The
    first candidate is that Sunday plus the offset modulo ``stride``. The default
    zero preserves the existing Sunday-derived grid.
    """
    if window < 1 or stride < 1 or reference_days < 1 or not 1 <= min_price_reference <= reference_days:
        raise ValueError("invalid window, stride, or reference coverage")
    if subset_size is not None and (
        not isinstance(subset_size, int) or isinstance(subset_size, bool) or subset_size < 1
    ):
        raise ValueError("subset_size must be a positive integer")
    if not isinstance(origin_shift_days, int) or isinstance(origin_shift_days, bool):
        raise ValueError("origin_shift_days must be an integer")
    if scale_fit_keys is not None and scales is not None:
        raise ValueError("scale_fit_keys and scales are mutually exclusive")
    key_columns = [*market_columns, "start"]
    if scale_fit_keys is not None:
        if not isinstance(scale_fit_keys, pd.DataFrame) or list(scale_fit_keys.columns) != key_columns:
            raise ValueError("scale_fit_keys must have exactly the selected key columns in order")
        if scale_fit_keys.empty or scale_fit_keys.isna().any().any() or scale_fit_keys.duplicated().any():
            raise ValueError("scale_fit_keys must contain nonempty unique non-null keys")
    if scales is not None:
        scales = np.asarray(scales, dtype=float).copy()
        if scales.shape != (2,) or not np.isfinite(scales).all() or (scales <= 0).any():
            raise ValueError("scales must contain two positive finite channel scales")
    cols = [*market_columns, date_column, price_column, activity_column]
    if observed_column is not None:
        cols.append(observed_column)
    df = history.loc[:, cols].copy()
    df[date_column] = pd.to_datetime(df[date_column], errors="raise")
    if df.empty or df[[*market_columns, date_column]].isna().any().any():
        raise ValueError("history must contain non-null market keys and dates")
    if (df[date_column] != df[date_column].dt.normalize()).any():
        raise ValueError("dates must be calendar dates without times")
    if df.duplicated([*market_columns, date_column]).any():
        raise ValueError("market-date must be unique")
    if observed_column is not None and (
        df[observed_column].isna().any() or not df[observed_column].isin([True, False]).all()
    ):
        raise ValueError("observation flag must be non-null boolean")
    df = df.sort_values([*market_columns, date_column]).reset_index(drop=True)
    for col in (price_column, activity_column):
        df[col] = pd.to_numeric(df[col], errors="raise").astype(float)
    rows, support, paths = [], [], {}
    group_arg = list(market_columns) if len(market_columns) > 1 else market_columns[0]
    for market, group in df.groupby(group_arg, sort=True, dropna=False):
        market = market if isinstance(market, tuple) else (market,)
        if len(group) > 1 and not group[date_column].diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
            raise ValueError(f"market {market} has nonconsecutive calendar dates")
        g = group.reset_index(drop=True).copy()
        price = g[price_column].to_numpy()
        finite = np.isfinite(price)
        positions = np.arange(len(g))
        valid_pos = positions[finite]
        prepared = np.full(len(g), np.nan)
        left = np.full(len(g), -1, dtype=int)
        right = np.full(len(g), -1, dtype=int)
        if len(valid_pos):
            inside = (positions >= valid_pos[0]) & (positions <= valid_pos[-1])
            prepared[inside] = np.interp(positions[inside], valid_pos, price[finite])
            left[inside] = valid_pos[np.searchsorted(valid_pos, positions[inside], side="right") - 1]
            right[inside] = valid_pos[np.searchsorted(valid_pos, positions[inside], side="left")]
        dates = g[date_column]
        sunday_offset = (6 - dates.iloc[0].weekday()) % 7
        offset = sunday_offset + origin_shift_days % stride
        first = dates.iloc[0] + pd.Timedelta(days=offset)
        for start in pd.date_range(first, dates.iloc[-1], freq=f"{stride}D"):
            i = int((start - dates.iloc[0]).days)
            r0, end = i - reference_days, i + window
            reasons = []
            if r0 < 0:
                reasons.append("incomplete_reference")
            if end > len(g):
                reasons.append("incomplete_episode")
            ref = g.iloc[max(0, r0) : i]
            ep = g.iloc[i : min(end, len(g))]
            refp = ref[price_column].to_numpy()
            goodp = np.isfinite(refp) & (refp > 0)
            refa = ref[activity_column].to_numpy()
            gooda = np.isfinite(refa) & (refa >= 0)
            price_ref = float(np.median(refp[goodp])) if goodp.sum() >= min_price_reference else np.nan
            activity_ref = float(refa.mean()) if len(refa) == reference_days and gooda.all() else np.nan
            if not np.isfinite(price_ref):
                reasons.append("price_reference_coverage")
            if not np.isfinite(activity_ref):
                reasons.append("activity_reference_coverage")
            elif activity_ref <= 0:
                reasons.append("zero_activity_reference")
            ep_price = prepared[i : min(end, len(g))]
            ep_activity = ep[activity_column].to_numpy()
            if len(ep_price) != window or not (np.isfinite(ep_price) & (ep_price > 0)).all():
                reasons.append("episode_price")
            if len(ep_activity) != window or not (np.isfinite(ep_activity) & (ep_activity >= 0)).all():
                reasons.append("episode_activity")
            key = (*market, start)
            row = dict(zip(market_columns, market, strict=True))
            row.update(
                start=start,
                eligible=not reasons,
                rejection_reasons=tuple(reasons),
                observed_reference_price_count=int(goodp.sum()),
                price_reference=price_ref,
                activity_reference=activity_ref,
                episode_observed_price_count=int(np.isfinite(price[i : min(end, len(g))]).sum()),
                episode_mean_activity=float(np.mean(ep_activity))
                if len(ep_activity) and np.isfinite(ep_activity).all()
                else np.nan,
            )
            rows.append(row)
            if not reasons:
                paths[key] = np.column_stack((np.log(ep_price / price_ref), np.log1p(ep_activity / activity_ref)))
            for j in range(max(0, r0), min(end, len(g))):
                s = dict(zip(market_columns, market, strict=True))
                s.update(
                    start=start,
                    date=dates.iloc[j],
                    role="reference" if j < i else "episode",
                    observed_price=price[j],
                    prepared_price=prepared[j],
                    interpolated=bool(not finite[j] and np.isfinite(prepared[j])),
                    interpolation_left=dates.iloc[left[j]] if left[j] >= 0 and not finite[j] else pd.NaT,
                    interpolation_right=dates.iloc[right[j]] if right[j] >= 0 and not finite[j] else pd.NaT,
                    source_observed=bool(g[observed_column].iloc[j]) if observed_column is not None else None,
                    observed_activity=g[activity_column].iloc[j],
                )
                support.append(s)
    candidates = pd.DataFrame(
        rows,
        columns=[
            *market_columns,
            "start",
            "eligible",
            "rejection_reasons",
            "observed_reference_price_count",
            "price_reference",
            "activity_reference",
            "episode_observed_price_count",
            "episode_mean_activity",
        ],
    )
    candidates["eligible"] = candidates["eligible"].astype(bool)
    daily = pd.DataFrame(
        support,
        columns=[
            *market_columns,
            "start",
            "date",
            "role",
            "observed_price",
            "prepared_price",
            "interpolated",
            "interpolation_left",
            "interpolation_right",
            "source_observed",
            "observed_activity",
        ],
    )
    eligible = candidates.loc[candidates.eligible].copy().reset_index(drop=True)
    if eligible.empty:
        if scale_fit_keys is not None:
            raise ValueError("scale_fit_keys must be selected eligible keys")
        keys = eligible[[*market_columns, "start"]].copy()
        empty = np.empty((0, window, 2))
        return JointPaths(
            candidates,
            keys,
            daily,
            empty,
            empty.copy(),
            np.full(2, np.nan) if scales is None else scales,
            ("price", activity_column),
            ("log(price / observed_reference_median)", "log1p(activity / reference_mean)"),
            seed if subset_size is not None else None,
            0,
            None,
            "unfitted" if scales is None else "provided",
            origin_shift_days,
        )
    if subset_size is not None and len(eligible) > subset_size:
        rng = np.random.default_rng(seed)
        strata = eligible.assign(_quarter=eligible.start.dt.to_period("Q"))
        buckets = [
            rng.permutation(index.to_numpy()).tolist()
            for _, index in strata.groupby([*market_columns, "_quarter"], sort=True).groups.items()
        ]
        rng.shuffle(buckets)
        chosen = []
        while len(chosen) < subset_size:
            for bucket in buckets:
                if bucket and len(chosen) < subset_size:
                    chosen.append(bucket.pop())
        eligible = eligible.iloc[sorted(chosen)].reset_index(drop=True)
    keys = eligible[[*market_columns, "start"]].copy()
    transformed = np.stack([paths[tuple(row)] for row in keys.itertuples(index=False, name=None)])
    if scales is not None:
        fit_keys = None
        scale_source = "provided"
    elif scale_fit_keys is None:
        fit_keys = keys.copy()
        scale_source = "selected"
        scales = transformed.std(axis=(0, 1))
    else:
        selected_index = pd.MultiIndex.from_frame(keys)
        fit_index = pd.MultiIndex.from_frame(scale_fit_keys)
        positions = selected_index.get_indexer(fit_index)
        if (positions < 0).any():
            raise ValueError("scale_fit_keys must be selected eligible keys")
        # Preserve selected-path ordering, independent of caller key ordering.
        positions.sort()
        fit_keys = keys.iloc[positions].reset_index(drop=True).copy()
        scale_source = "training"
        scales = transformed[positions].std(axis=(0, 1))
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise ValueError("pooled channel standard deviations must be positive and finite")
    return JointPaths(
        candidates,
        keys,
        daily,
        transformed,
        transformed / scales,
        scales,
        ("price", activity_column),
        ("log(price / observed_reference_median)", "log1p(activity / reference_mean)"),
        seed if subset_size is not None else None,
        len(keys) ** 2 * np.dtype(np.float64).itemsize,
        fit_keys,
        scale_source,
        origin_shift_days,
    )


def summarize_joint_paths(paths: JointPaths) -> pd.DataFrame:
    """Summarize original observations for all eligible candidates, in key order.

    Peak timings are mean zero-based calendar-day positions within the episode;
    ties are averaged and constant observed channels have unavailable timing.
    Coverage is the fraction of episode days with positive finite observed price.
    ``support_start`` and ``support_end`` are inclusive and include the reference,
    episode, and any external interpolation endpoints used by episode prices.
    Summaries are descriptive and do not affect eligibility or subset selection.
    """
    key_columns = paths.keys.columns.tolist()
    features = [
        "median_log_price_relative",
        "final_log_price_relative",
        "observed_log_price_change",
        "observed_log_price_range",
        "price_peak_timing",
        "mean_activity_ratio",
        "peak_activity_share",
        "activity_peak_timing",
        "observed_price_coverage",
        "support_start",
        "support_end",
    ]
    eligible = paths.candidates.loc[paths.candidates.eligible]
    if eligible.empty:
        return pd.DataFrame(columns=[*key_columns, *features])
    daily_groups = {
        key if isinstance(key, tuple) else (key,): group.sort_values("date")
        for key, group in paths.daily.groupby(key_columns, sort=False, dropna=False)
    }
    rows = []
    for candidate in eligible.to_dict("records"):
        key = tuple(candidate[column] for column in key_columns)
        daily = daily_groups[key]
        episode = daily.loc[daily.role == "episode"]
        prices = episode.observed_price.to_numpy(dtype=float)
        valid = np.isfinite(prices) & (prices > 0)
        log_prices = np.full(len(prices), np.nan)
        log_prices[valid] = np.log(prices[valid])
        observed = log_prices[valid]
        activity = episode.observed_activity.to_numpy(dtype=float)

        def peak_timing(values, mask):
            observed_values = values[mask]
            if len(observed_values) < 2 or np.min(observed_values) == np.max(observed_values):
                return np.nan
            return float(np.flatnonzero(mask & (values == np.max(observed_values))).mean())

        dependencies = episode.loc[episode.interpolated, ["interpolation_left", "interpolation_right"]]
        support_dates = pd.concat([daily.date, dependencies.stack()], ignore_index=True)
        reference_log = np.log(candidate["price_reference"])
        total = activity.sum()
        row = {column: candidate[column] for column in key_columns}
        row.update(
            median_log_price_relative=float(np.median(observed) - reference_log) if len(observed) else np.nan,
            final_log_price_relative=float(log_prices[-1] - reference_log) if valid[-1] else np.nan,
            observed_log_price_change=float(log_prices[-1] - log_prices[0]) if valid[0] and valid[-1] else np.nan,
            observed_log_price_range=float(np.ptp(observed)) if len(observed) else np.nan,
            price_peak_timing=peak_timing(log_prices, valid),
            mean_activity_ratio=float(activity.mean() / candidate["activity_reference"]),
            peak_activity_share=float(activity.max() / total) if total > 0 else np.nan,
            activity_peak_timing=peak_timing(activity, np.isfinite(activity)),
            observed_price_coverage=float(valid.mean()),
            support_start=support_dates.min(),
            support_end=support_dates.max(),
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=[*key_columns, *features])


@njit
def _dependent_dtw(a, b, band):
    n, m = len(a), len(b)
    prev = np.full(m + 1, np.inf)
    prev[0] = 0.0
    for i in range(1, n + 1):
        curr = np.full(m + 1, np.inf)
        for j in range(max(1, i - band), min(m, i + band) + 1):
            cost = 0.0
            for k in range(a.shape[1]):
                cost += (a[i - 1, k] - b[j - 1, k]) ** 2
            curr[j] = cost + min(prev[j], curr[j - 1], prev[j - 1])
        prev = curr
    return np.sqrt(prev[m])


def dependent_dtw(a: np.ndarray, b: np.ndarray, band: int = 2) -> float:
    """Root sum of squared paired-vector costs under one shared warping path."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.ndim != 2 or b.ndim != 2 or not len(a) or not len(b) or a.shape[1] != b.shape[1] or a.shape[1] == 0:
        raise ValueError("paths must be nonempty 2D arrays with matching channels")
    if not isinstance(band, int) or band < 0 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("band must be nonnegative and paths must be finite")
    return float(_dependent_dtw(a, b, band))


def pairwise_dtw(tensor: np.ndarray, band: int = 2) -> np.ndarray:
    """Compute an in-memory symmetric matrix; caller controls the population."""
    tensor = np.asarray(tensor, dtype=float)
    if tensor.ndim != 3 or not tensor.shape[0] or not tensor.shape[1] or not tensor.shape[2]:
        raise ValueError("tensor must be a nonempty 3D array")
    if not isinstance(band, int) or band < 0 or not np.isfinite(tensor).all():
        raise ValueError("band must be nonnegative and tensor must be finite")
    result = np.zeros((len(tensor), len(tensor)))
    for i in range(len(tensor)):
        for j in range(i):
            result[i, j] = result[j, i] = _dependent_dtw(tensor[i], tensor[j], band)
    return result
