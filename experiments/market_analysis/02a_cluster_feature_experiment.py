# /// script
# dependencies = [
#     "marimo",
#     "plotly==7.1.0",
#     "scikit-learn==1.9.1",
#     "umap-learn==0.6.0",
# ]
# requires-python = ">=3.13"
# ///

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from datetime import date, datetime, timedelta

    return date, datetime, go, make_subplots, mo, timedelta


@app.cell(hide_code=True)
def _(
    holdout_gates,
    holdout_levels,
    holdout_outcome,
    holdout_scores,
    holdout_seeds,
    holdout_widths,
    mo,
    weak_spike_onsets,
):
    _recall = {}
    for _level in holdout_levels:
        _recall[_level] = [sum(row["spike hits"] for row in holdout_scores[_level, 100, method])
                          / (len(holdout_seeds) * len(weak_spike_onsets)) for method in holdout_widths]
    _n = len(holdout_seeds)
    _spikes = _n * len(weak_spike_onsets)
    _lines = []
    for _level, _result in holdout_outcome.items():
        _flat, _hits, _weekday = (_result[key] for key in ("flat runs", "added hits", "weekday passes"))
        _cells = [f"{_flat}/{_n} · {'pass' if _flat <= holdout_gates['max flat runs'] else '**miss**'}",
                  f"{_hits:+d}/{_spikes:,} · {'pass' if _hits >= holdout_gates['min added hits'] else '**miss**'}",
                  f"{_weekday}/{_n} · {'pass' if _weekday >= holdout_gates['min weekday passes'] else '**miss**'}"]
        _lines.append(f"| {_level.title()} | " + " | ".join(_cells) + " |")
    _scorecard = "\n".join(_lines)
    mo.md(f"""# Price shapes under noise

    ## Locked bands · {_n} holdout seeds ({holdout_seeds[0]}–{holdout_seeds[-1]})

    The median-of-five rule found more 10% spikes: recall rose from **{_recall['typical'][0]:.1%} to {_recall['typical'][1]:.1%}** under typical jitter and from **{_recall['stress'][0]:.1%} to {_recall['stress'][1]:.1%}** under stress. **Neither noise level passed all three gates.**

    | Holdout | Flat paths with a run ≤{holdout_gates['max flat runs']}/{_n} | Added 10% spike-day hits ≥+{holdout_gates['min added hits']}/{_spikes:,} | All-seven weekday passes ≥{holdout_gates['min weekday passes']}/{_n} |
    | :-- | --: | --: | --: |
    {_scorecard}

    All three preset gates must pass within a noise level. Added hits are the paired difference from first-price p90, not total recall.""")
    return


@app.cell(hide_code=True)
def _(
    jitter_seeds,
    mo,
    shape_split_dev_comparison,
    shape_split_failure_counts,
    shape_split_gates,
):
    _duration, _recurrence, _reversal, _size = shape_split_dev_comparison["typical"]
    _n = len(jitter_seeds)
    _r = shape_split_failure_counts["Reversal"]
    _s = shape_split_failure_counts["Size equivalence"]
    _rev_misses = _n - _r["Pass"]
    _size_misses = _n - _s["Pass"]
    mo.md(f"""## Shape-only distance · {_n} development seeds ({jitter_seeds[0]}–{jitter_seeds[-1]}), typical jitter

    Leaving signed peak out of the distance, while keeping it as a separate magnitude measure, raised duration passes from **{_duration['benchmark passes']}/{_n} to {_duration['shape-only passes']}/{_n}**. Recurrence stayed at **{_recurrence['shape-only passes']}/{_n}**. **Shape-only distance did not advance:** reversal stayed at **{_reversal['shape-only passes']}/{_n}** and size equivalence rose from **{_size['benchmark passes']}/{_n} to {_size['shape-only passes']}/{_n}**; each needed **{shape_split_gates['reversal']}/{_n}**.

    On those same seeds, all **{_rev_misses}** reversal failures had the expected peaks and observed timing but missed the distance margin. Of **{_size_misses}** size-equivalence failures, **{_s['Both below six']}** fell short on both detection and distance, and **{_s['Distance only']}** on distance alone. No new holdout was run. The fitted clean pipeline is unchanged.""")
    return


@app.cell(hide_code=True)
def _(
    jitter_seeds,
    local_peak_dev_gates,
    local_peak_dev_summary,
    local_peak_trace_summary,
    mo,
    weekday_ablation_rows,
):
    _restoration = next(row for row in weekday_ablation_rows
                        if (row["noise"], row["rule"], row["restored clean coordinate"]) == ("typical", "Median-5 p90", "Signed peak"))
    _typical = local_peak_dev_summary["typical"]
    _persistent = local_peak_trace_summary[-1]
    _n = len(jitter_seeds)
    earlier_peak_correction_summary = mo.md(f"""## Why the weekday gate stayed hard — development only

    On the {_n} typical-jitter development seeds, replacing only the measured signed peak with its known clean value turned **{_restoration['failed → pass']} of {_n - _restoration['original pass / 64']}** weekday failures into passes.

    **The adjacent-price correction did not advance.** Ordinary weekday passes stayed at **{_typical['ordinary pass']}/{_n}**; protected passes reached **{_typical['protected pass']}/{_n}** ({local_peak_dev_gates['protected weekday passes']} required), and magnitude separation reached **{_typical['candidate magnitude passes']}/{_n}** ({local_peak_dev_gates['magnitude separation passes']} required).

    More accurate peaks did not guarantee better shape comparisons: **{_persistent['lower 150-spike MAE']} of the {_persistent['seeds']}** seeds that still failed had lower average peak error across their seven planted 150 spikes.""")
    return (earlier_peak_correction_summary,)


@app.cell(hide_code=True)
def _(
    local_peak_correction_view,
    mo,
    paired_weekday_margins_view,
    peak_restoration_view,
):
    earlier_peak_correction_details = mo.accordion({"Development evidence: peak restoration, correction scores, and paired margins": mo.accordion({
        "Peak restoration and weekday failure breakdown": peak_restoration_view,
        "Adjacent-price correction: development gates and peak errors": local_peak_correction_view,
        "Paired weekday margins: shift distances and plateau cap": paired_weekday_margins_view,
    }, multiple=True)})
    return (earlier_peak_correction_details,)


@app.cell(hide_code=True)
def _(holdout_widths, mo, opening_p90_gates):
    _gates = opening_p90_gates
    band_settings_view = mo.md(f"""## Why these settings

    - **Why a band:** Exact baseline equality gave all 64 noisy development flats a run at each noise level. A narrower band keeps more weak spikes but admits more false runs. The widths came from p80/p90/p95 of each typical flat path’s **maximum** log departure over 21 days, not daily-return percentiles. A spike is recovered only if its planted day lies above the band.
    - **Why median-5 p90 advanced:** The median of the first five prices makes the run reference less dependent on one opening day; signed peak remains relative to the first price. At p90, typical development (seeds 0–63) preserved the clean features, with **{_gates['flat paths with a run']}/64** flat runs (≤7), **{_gates['additional spike hits']:+d}/448** hits (≥+23), and **{_gates['passing weekday draws']}/64** weekday passes (≥35). Each reference kept its own width—**{holdout_widths['First-price p90']:.6f}** vs **{holdout_widths['Median-5 p90']:.6f}** log units—for **512 fresh seeds (64–575)**. Stress was not a tuning target.
    - **What this tests:** Quiet-opening, constant-activity synthetic paths, not market detection. Typical jitter is Gaussian AR(1) in log price, calibrated to summaries of observed Forge returns, not labeled noise; stress rescales those same offsets and does not fit heavy tails. The generator does not reproduce the observed mass of zero returns. Weekdays and bases reuse a seed’s background. Rates use base 100 only; intervals resample whole paired seeds.""")
    return (band_settings_view,)


@app.cell(hide_code=True)
def _(date, timedelta):
    templates = {
        "One-day spike (150)": [100, 150, 100, 100, 100],
        "Two-day plateau": [100, 150, 150, 100, 100],
        "Step that holds": [100, 150, 150, 150, 150],
        "Gradual rise that holds": [100, 112, 125, 137, 150],
        "Two distinct spikes": [100, 150, 100, 150, 100],
        "Gradual rise, abrupt reversal": [100, 112, 125, 150, 100],
        "Abrupt rise, gradual recovery": [100, 150, 125, 112, 100],
        "One-day spike (110)": [100, 110, 100, 100, 100],
        "One-day spike (125)": [100, 125, 100, 100, 100],
        "One-day dip (80)": [100, 80, 100, 100, 100],
    }
    weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    dates = [date(2023, 12, 31) + timedelta(days=i) for i in range(21)]
    # The template's first 100 is the day before onset, not the onset itself.
    price_histories = tuple(
        tuple([100] * (7 + day_index) + values[1:] + [values[-1]] * (21 - (7 + day_index) - 4))
        for values in templates.values()
        for day_index in range(7)
    ) + ((100,) * 21,)
    evaluation_metadata = tuple(
        {"shape": shape, "onset_date": dates[7 + day_index], "weekday": weekday}
        for shape in templates
        for day_index, weekday in enumerate(weekdays)
    ) + ({"shape": "Flat reference", "onset_date": None, "weekday": None},)
    history_index = {(item["shape"], item["weekday"]): index for index, item in enumerate(evaluation_metadata)}
    return (
        dates,
        evaluation_metadata,
        history_index,
        price_histories,
        templates,
        weekdays,
    )


@app.cell(hide_code=True)
def _(dates, datetime, go, make_subplots, price_histories, timedelta):
    # Both comparison views use the gallery's scales and boundary.
    def comparison_figure(history_ids, labels):
        figure = make_subplots(rows=1, cols=len(history_ids), shared_yaxes=True, subplot_titles=labels, horizontal_spacing=0.04)
        for col, history_id in enumerate(history_ids, start=1):
            figure.add_trace(go.Scatter(x=dates, y=price_histories[history_id], mode="lines+markers", line={"color": "#3274a1"}, marker={"size": 4}, showlegend=False, hovertemplate="%{x|%a %d %b}<br>Price: %{y}<extra></extra>"), row=1, col=col)
            figure.add_vline(x=datetime.combine(dates[13], datetime.min.time()) + timedelta(hours=12), line_dash="dash", line_color="#a33", row=1, col=col)
        figure.update_xaxes(matches="x", range=[datetime.combine(dates[0], datetime.min.time()) - timedelta(hours=12), datetime.combine(dates[-1], datetime.min.time()) + timedelta(hours=12)], tickformat="%d %b", dtick=604800000)
        figure.update_xaxes(matches=None, row=1, col=1)
        figure.update_yaxes(range=[70, 160], title_text="Price", row=1, col=1)
        figure.update_layout(height=360, margin={"t": 100, "b": 45}, template="plotly_white")
        return figure

    return (comparison_figure,)


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## What counts as a weekday pass?

    Compare histories on shared scales. With the defaults, left → middle moves the spike by one weekday; middle → right adds one day at peak. The dashed line marks the Saturday/Sunday boundary. Each path has 21 days and a full quiet opening week; the flat path ignores the weekday selector.
    """)
    return


@app.cell(hide_code=True)
def _(mo, templates, weekdays):
    shape_options = ["Flat reference", *templates]
    shape_left = mo.ui.dropdown(shape_options, value="One-day spike (150)", label="Left shape")
    day_left = mo.ui.dropdown(weekdays, value="Friday", label="Left onset")
    shape_middle = mo.ui.dropdown(shape_options, value="One-day spike (150)", label="Middle shape")
    day_middle = mo.ui.dropdown(weekdays, value="Saturday", label="Middle onset")
    shape_right = mo.ui.dropdown(shape_options, value="Two-day plateau", label="Right shape")
    day_right = mo.ui.dropdown(weekdays, value="Saturday", label="Right onset")
    mo.hstack([mo.vstack([shape_left, day_left]), mo.vstack([shape_middle, day_middle]), mo.vstack([shape_right, day_right])], align="start")
    return (
        day_left,
        day_middle,
        day_right,
        shape_left,
        shape_middle,
        shape_right,
    )


@app.cell(hide_code=True)
def _(
    comparison_figure,
    day_left,
    day_middle,
    day_right,
    history_index,
    shape_left,
    shape_middle,
    shape_right,
):
    _selected = [(shape_left.value, day_left.value), (shape_middle.value, day_middle.value), (shape_right.value, day_right.value)]
    _ids = [history_index[(shape, None if shape == "Flat reference" else day)] for shape, day in _selected]
    _labels = [f"{shape}<br>{day if shape != 'Flat reference' else 'No onset'}" for shape, day in _selected]
    comparison_figure(_ids, _labels)
    return


@app.cell(hide_code=True)
def _(mo, smallest_margin, weekday_checks):
    mo.md(f"""
    Across the seven clean 150-spike anchors, the farthest shifted spike is **{max(row['farthest_shift'] for row in weekday_checks):g}** away and the same-onset plateau is **{smallest_margin:.6f}** away in four-feature space. A noisy seed passes only if the plateau is strictly farther than every shifted spike for **all seven** anchors. This tests one duration contrast, not general shape stability.
    """)
    return


@app.cell(hide_code=True)
def _(clean_neighbors_view, mo, weekday_evidence_view):
    mo.accordion({"Weekdays and nearest neighbors": mo.vstack([weekday_evidence_view, clean_neighbors_view])})
    return


@app.cell(hide_code=True)
def _(mo):
    clean_feature_definitions = mo.md("""**Clean features.** Signed peak is the first maximum-absolute log price displacement from day one; its sign is retained. Persistence is the longest uninterrupted nonbaseline run; recurrence counts runs separated by observed baseline returns. Days to peak is elapsed days from the start of the peak’s run. Flat timing is N/A; fitting uses the mean observed timing as a numeric placeholder. All four columns are centered and scaled using population standard deviations over 71 clean paths. Adjacent off-baseline observations belong to one run; a hold ends at the observation boundary.

    **Other timing candidates.** First-day peak share is the absolute run-start displacement divided by the absolute peak. Days to return is time from peak to an observed baseline return. A timing candidate adds a distinction only when both values are observed and differ.""")
    return (clean_feature_definitions,)


@app.cell(hide_code=True)
def _(price_histories):
    from math import log
    from itertools import groupby

    def extract_price_features(history):
        logs = [log(price / history[0]) for price in history]
        peak_index = max(range(len(logs)), key=lambda index: abs(logs[index]))
        lengths = tuple(sum(1 for _ in run) for off_baseline, run in groupby(history, key=lambda price: price != history[0]) if off_baseline)
        if logs[peak_index] == 0:
            timing = {"days_to_peak": None, "first_day_peak_share": None, "days_to_return": None}
        else:
            run_start = peak_index
            while run_start > 0 and history[run_start - 1] != history[0]:
                run_start -= 1
            return_index = next((index for index in range(peak_index + 1, len(history)) if history[index] == history[0]), None)
            timing = {"days_to_peak": peak_index - run_start, "first_day_peak_share": abs(logs[run_start]) / abs(logs[peak_index]), "days_to_return": None if return_index is None else return_index - peak_index}
        return logs[peak_index], max(lengths, default=0), len(lengths), timing

    observed_features = tuple(extract_price_features(history) for history in price_histories)
    peak_displacements = tuple(row[0] for row in observed_features)
    return extract_price_features, log, observed_features, peak_displacements


@app.cell(hide_code=True)
def _(observed_features):
    persistence_days = tuple(row[1] for row in observed_features)
    recurrence_runs = tuple(row[2] for row in observed_features)
    return persistence_days, recurrence_runs


@app.cell(hide_code=True)
def _(observed_features):
    # Candidate rows are aligned with price_histories by integer history ID.
    timing_candidates = tuple(row[3] for row in observed_features)
    return (timing_candidates,)


@app.cell(hide_code=True)
def _(
    peak_displacements,
    persistence_days,
    price_histories,
    recurrence_runs,
    timing_candidates,
):
    from math import dist, sqrt

    # Rows are indexed by history ID; labels never enter preprocessing.
    feature_names = ("signed_peak", "persistence_days", "recurrence_runs", "days_to_peak")
    _observed_timing = [row["days_to_peak"] for row in timing_candidates if row["days_to_peak"] is not None]
    timing_fill = sum(_observed_timing) / len(_observed_timing)
    raw_feature_rows = tuple((peak_displacements[i], persistence_days[i], recurrence_runs[i], timing_candidates[i]["days_to_peak"] if timing_candidates[i]["days_to_peak"] is not None else timing_fill) for i in range(len(price_histories)))
    feature_means = tuple(sum(row[col] for row in raw_feature_rows) / len(raw_feature_rows) for col in range(len(feature_names)))
    feature_scales = tuple(sqrt(sum((row[col] - feature_means[col]) ** 2 for row in raw_feature_rows) / len(raw_feature_rows)) for col in range(len(feature_names)))
    prepared_feature_rows = tuple(tuple((row[col] - feature_means[col]) / feature_scales[col] for col in range(len(feature_names))) for row in raw_feature_rows)
    cohort_distances = tuple(tuple(dist(left, right) for right in prepared_feature_rows) for left in prepared_feature_rows)
    return (
        cohort_distances,
        dist,
        feature_means,
        feature_scales,
        prepared_feature_rows,
        sqrt,
        timing_fill,
    )


@app.cell(hide_code=True)
def _(
    dist,
    extract_price_features,
    feature_means,
    feature_scales,
    history_index,
    prepared_feature_rows,
    price_histories,
    timing_fill,
    weekdays,
):
    # Proportional histories retain base-100 row order and use the same extractor.
    replay_histories = {base: tuple(tuple(price * (base / 100) for price in history) for history in price_histories) for base in (100, 10, 1)}
    replay_features = {base: tuple(extract_price_features(history) for history in histories) for base, histories in replay_histories.items()}
    replay_prepared_rows = {base: tuple(tuple((value - feature_means[col]) / feature_scales[col] for col, value in enumerate((row[0], row[1], row[2], row[3]["days_to_peak"] if row[3]["days_to_peak"] is not None else timing_fill))) for row in rows) for base, rows in replay_features.items()}
    replay_summary = []
    for _base, _rows in replay_features.items():
        _baseline = replay_features[100]
        _changes = [max(abs(row[col] - reference[col]) for row, reference in zip(_rows, _baseline)) for col in range(3)]
        _timing_pairs = [(row[3]["days_to_peak"], reference[3]["days_to_peak"]) for row, reference in zip(_rows, _baseline)]
        _timing_match = all((left is None) == (right is None) for left, right in _timing_pairs)
        _timing_change = max(abs(left - right) for left, right in _timing_pairs if left is not None and right is not None)
        _matched_distance = max(dist(row, reference) for row, reference in zip(replay_prepared_rows[_base], prepared_feature_rows))
        _margins = []
        for _day in weekdays:
            _anchor = history_index[("One-day spike (150)", _day)]
            _farthest = max(dist(replay_prepared_rows[_base][_anchor], replay_prepared_rows[_base][history_index[("One-day spike (150)", other)]]) for other in weekdays if other != _day)
            _plateau = history_index[("Two-day plateau", _day)]
            _margins.append(dist(replay_prepared_rows[_base][_anchor], replay_prepared_rows[_base][_plateau]) - _farthest)
        replay_summary.append({"base": _base, "max peak change": _changes[0], "max persistence change": _changes[1], "max recurrence change": _changes[2], "max timing change": _timing_change, "timing N/A matches": _timing_match, "max matched distance": _matched_distance, "smallest weekday margin": min(_margins)})
    return (
        replay_features,
        replay_histories,
        replay_prepared_rows,
        replay_summary,
    )


@app.cell(hide_code=True)
def _(sqrt):
    from math import exp
    from random import Random
    from statistics import NormalDist, median

    # Forge per-item medians: summaries of observed returns, not labeled noise.
    calibration_median_abs_return = 0.015949
    calibration_p90_abs_return = 0.073609
    calibration_lag1_correlation = -0.297349
    calibration_zero_fraction = 0.036774
    jitter_phi = 1 + 2 * calibration_lag1_correlation
    jitter_return_sd = calibration_median_abs_return / NormalDist().inv_cdf(0.75)
    jitter_level_sd = jitter_return_sd / sqrt(2 * (1 - jitter_phi))
    jitter_innovation_sd = jitter_level_sd * sqrt(1 - jitter_phi ** 2)
    jitter_stress_multiplier = calibration_p90_abs_return / (NormalDist().inv_cdf(0.95) * jitter_return_sd)
    def make_jitter_multipliers(seeds):
        offsets = {}
        for seed in seeds:
            rng = Random(seed)
            levels = [rng.gauss(0, jitter_level_sd)]
            for day in range(1, 21):
                levels.append(jitter_phi * levels[-1] + rng.gauss(0, jitter_innovation_sd))
            offsets[seed] = tuple(level - levels[0] for level in levels)
        return {
            level: {seed: tuple(exp(scale * offset) for offset in path) for seed, path in offsets.items()}
            for level, scale in (("typical", 1.0), ("stress", jitter_stress_multiplier))
        }


    jitter_seeds = tuple(range(64))
    jitter_multipliers = make_jitter_multipliers(jitter_seeds)
    return (
        Random,
        calibration_lag1_correlation,
        calibration_median_abs_return,
        calibration_p90_abs_return,
        calibration_zero_fraction,
        jitter_innovation_sd,
        jitter_level_sd,
        jitter_multipliers,
        jitter_phi,
        jitter_seeds,
        jitter_stress_multiplier,
        make_jitter_multipliers,
        median,
    )


@app.cell(hide_code=True)
def _(
    extract_price_features,
    feature_means,
    feature_scales,
    jitter_multipliers,
    jitter_seeds,
    replay_histories,
    timing_fill,
):
    # level → base → seed → history ID; every seed's background is shared.
    noise_histories = {level: {base: {seed: tuple(tuple(price * factor for price, factor in zip(history, jitter_multipliers[level][seed])) for history in histories) for seed in jitter_seeds} for base, histories in replay_histories.items()} for level in jitter_multipliers}
    noise_features = {level: {base: {seed: tuple(extract_price_features(history) for history in histories) for seed, histories in draws.items()} for base, draws in bases.items()} for level, bases in noise_histories.items()}
    noise_prepared = {level: {base: {seed: tuple(tuple((value - feature_means[col]) / feature_scales[col] for col, value in enumerate((row[0], row[1], row[2], row[3]["days_to_peak"] if row[3]["days_to_peak"] is not None else timing_fill))) for row in rows) for seed, rows in draws.items()} for base, draws in bases.items()} for level, bases in noise_features.items()}
    return noise_features, noise_histories, noise_prepared


@app.cell(hide_code=True)
def _(
    dist,
    history_index,
    jitter_multipliers,
    jitter_seeds,
    median,
    noise_features,
    noise_prepared,
    replay_features,
    replay_histories,
    replay_prepared_rows,
    weekdays,
):
    noise_summary = []
    noise_feature_summary = []
    for _level in jitter_multipliers:
        for _base in replay_histories:
            _drifts = [[], [], [], []]
            _timing_na_changes = 0
            _displacements = []
            _margins = []
            _flat_lengths = []
            for _seed in jitter_seeds:
                _rows = noise_features[_level][_base][_seed]
                _prepared = noise_prepared[_level][_base][_seed]
                for _id, _row in enumerate(_rows):
                    _clean = replay_features[_base][_id]
                    for _col in range(3):
                        _drifts[_col].append(abs(_row[_col] - _clean[_col]))
                    _before, _after = _clean[3]["days_to_peak"], _row[3]["days_to_peak"]
                    _timing_na_changes += (_before is None) != (_after is None)
                    if _before is not None and _after is not None:
                        _drifts[3].append(abs(_after - _before))
                    _displacements.append(dist(_prepared[_id], replay_prepared_rows[_base][_id]))
                _seed_margins = []
                for _day in weekdays:
                    _anchor = history_index[("One-day spike (150)", _day)]
                    _farthest = max(dist(_prepared[_anchor], _prepared[history_index[("One-day spike (150)", other)]]) for other in weekdays if other != _day)
                    _plateau = history_index[("Two-day plateau", _day)]
                    _seed_margins.append(dist(_prepared[_anchor], _prepared[_plateau]) - _farthest)
                _margins.append(min(_seed_margins))
                _flat_lengths.append(_rows[history_index[("Flat reference", None)]][1])
            noise_summary.append({"level": _level, "base": _base, "median displacement": median(_displacements), "max displacement": max(_displacements), "worst weekday margin": min(_margins), "all seven pass seeds": sum(margin > 0 for margin in _margins) / len(jitter_seeds), "flat any-run fraction": sum(length > 0 for length in _flat_lengths) / len(jitter_seeds), "flat run length min/median/max": f"{min(_flat_lengths)}/{median(_flat_lengths)}/{max(_flat_lengths)}"})
            for _name, _values, _unit in zip(["signed peak", "persistence", "recurrence", "days to peak"], _drifts, ["log units", "days", "runs", "days"]):
                noise_feature_summary.append({"level": _level, "base": _base, "feature": _name, "unit": _unit, "comparable rows": len(_values), "changed rows": sum(value != 0 for value in _values), "median absolute drift": median(_values), "max absolute drift": max(_values), "timing N/A changes": _timing_na_changes if _name == "days to peak" else None})
    return noise_feature_summary, noise_summary


@app.cell(hide_code=True)
def _(dist, evaluation_metadata, history_index, noise_prepared):
    _query = history_index[("One-day spike (150)", "Saturday")]
    _draw = noise_prepared["typical"][100][0]
    _order = sorted((item for item in range(len(_draw)) if item != _query), key=lambda item: dist(_draw[_query], _draw[item]))
    _cutoff = dist(_draw[_query], _draw[_order[4]])
    noise_example_neighbors = [{"rank": 1 + sum(dist(_draw[_query], _draw[other]) < dist(_draw[_query], _draw[item]) for other in _order), "history ID": item, "shape": evaluation_metadata[item]["shape"], "weekday": evaluation_metadata[item]["weekday"] or "—", "distance": dist(_draw[_query], _draw[item])} for item in _order if dist(_draw[_query], _draw[item]) <= _cutoff]
    return (noise_example_neighbors,)


@app.cell(hide_code=True)
def _(prepared_feature_rows):
    from sklearn.decomposition import PCA
    from umap import UMAP

    pca_model = PCA(n_components=2)
    pca_coordinates = pca_model.fit_transform(prepared_feature_rows)
    pca_variance_ratios = tuple(float(value) for value in pca_model.explained_variance_ratio_)
    umap_coordinates = UMAP(n_components=2, n_neighbors=15, min_dist=0.1, metric="euclidean", random_state=42, n_jobs=1, compatibility_layout=True).fit_transform(prepared_feature_rows)
    return pca_coordinates, pca_variance_ratios, umap_coordinates


@app.cell(hide_code=True)
def _(
    history_index,
    mo,
    peak_displacements,
    persistence_days,
    recurrence_runs,
):
    persistence_evidence = [{"history ID": history_index[(shape, day)], "shape": shape, "weekday": day or "—", "signed peak": peak_displacements[history_index[(shape, day)]], "persistence days": persistence_days[history_index[(shape, day)]], "recurrence runs": recurrence_runs[history_index[(shape, day)]]} for shape, day in [("One-day spike (110)", "Saturday"), ("One-day spike (150)", "Saturday"), ("One-day spike (125)", "Saturday"), ("One-day dip (80)", "Saturday"), ("Flat reference", None), ("Step that holds", "Sunday"), ("Step that holds", "Saturday"), ("Two-day plateau", "Saturday"), ("Two distinct spikes", "Saturday"), ("Gradual rise, abrupt reversal", "Saturday"), ("Abrupt rise, gradual recovery", "Saturday")]]
    matched_controls_view = mo.vstack([mo.md("### Matched controls: actual feature values. The plateau persists for 2 days; two separated spikes and one spike each persist for 1. The separated spikes have two runs versus one for a single spike. The time-reversed pair ties on all three features. Signed peak continues to distinguish size, direction, and flat."), mo.ui.table(persistence_evidence, selection=None, page_size=12)])
    return (matched_controls_view,)


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## Why add days to peak?

    Signed peak, longest run and run count tie both the step/ramp holds and the time-reversed pair at every matched onset. Adding days to peak distinguishes both at **7/7**; first-day peak share does too. Days to return cannot distinguish the holds because neither return is observed.

    **Read the map:** Each off-diagonal cell counts matched weekdays with different feature values; **0/7** means always tied, not misclassified. It reuses one flat control across the seven shifts. Click a cell to compare its two paths, and use the onset selector to choose which paths to show.
    """)
    return


@app.cell(hide_code=True)
def _(
    history_index,
    peak_displacements,
    persistence_days,
    recurrence_runs,
    templates,
    timing_candidates,
    weekdays,
):
    map_shapes = list(templates) + ["Flat reference"]
    map_modes = {"Three-feature diagnostic": None, "Three features + days to peak": "days_to_peak", "Three features + first-day peak share": "first_day_peak_share", "Three features + days to return": "days_to_return"}
    map_counts = {}
    for _mode, _candidate in map_modes.items():
        _matrix = []
        for _left in map_shapes:
            _row = []
            for _right in map_shapes:
                if _left == _right:
                    _row.append(None)
                    continue
                _count = 0
                for _day in weekdays:
                    _i = history_index[(_left, None if _left == "Flat reference" else _day)]
                    _j = history_index[(_right, None if _right == "Flat reference" else _day)]
                    _different = (peak_displacements[_i], persistence_days[_i], recurrence_runs[_i]) != (peak_displacements[_j], persistence_days[_j], recurrence_runs[_j])
                    if _candidate is not None:
                        _a, _b = timing_candidates[_i][_candidate], timing_candidates[_j][_candidate]
                        _different = _different or (_a is not None and _b is not None and _a != _b)
                    _count += int(_different)
                _row.append(_count)
            _matrix.append(_row)
        map_counts[_mode] = _matrix
    return map_counts, map_modes, map_shapes


@app.cell(hide_code=True)
def _(map_modes, mo, weekdays):
    map_mode = mo.ui.dropdown(list(map_modes), value="Three-feature diagnostic", label="Representation")
    map_day = mo.ui.dropdown(weekdays, value="Saturday", label="Matched onset for paths")
    mo.hstack([map_mode, map_day], justify="start")
    return map_day, map_mode


@app.cell(hide_code=True)
def _(go, map_counts, map_mode, map_shapes, mo):
    _figure = go.Figure(go.Heatmap(z=map_counts[map_mode.value], x=map_shapes, y=map_shapes, zmin=0, zmax=7, colorscale="Blues", text=[["" if value is None else f"{value}/7" for value in row] for row in map_counts[map_mode.value]], texttemplate="%{text}", hovertemplate="%{y}<br>vs %{x}<br>%{text}<extra></extra>", colorbar={"title": "Different"}))
    _figure.update_layout(height=690, margin={"l": 220, "b": 200, "t": 20}, template="plotly_white", xaxis={"tickangle": -45}, yaxis={"autorange": "reversed"}, clickmode="event+select")
    collision_map = mo.ui.plotly(_figure)
    collision_map
    return (collision_map,)


@app.cell(hide_code=True)
def _(
    collision_map,
    comparison_figure,
    history_index,
    map_day,
    map_shapes,
    mo,
    peak_displacements,
    persistence_days,
    recurrence_runs,
    timing_candidates,
):
    _points = collision_map.points
    selected_shapes = (_points[-1]["y"], _points[-1]["x"]) if _points and _points[-1].get("x") in map_shapes and _points[-1].get("y") in map_shapes and _points[-1]["x"] != _points[-1]["y"] else ("Gradual rise, abrupt reversal", "Abrupt rise, gradual recovery")
    selected_ids = [history_index[(shape, None if shape == "Flat reference" else map_day.value)] for shape in selected_shapes]
    selected_detail_rows = []
    for _shape, _id in zip(selected_shapes, selected_ids):
        _timing = timing_candidates[_id]
        _missing = "Not applicable (flat)" if _shape == "Flat reference" else "Unobserved return"
        selected_detail_rows.append({"history ID": _id, "shape": _shape, "signed peak": peak_displacements[_id], "persistence days": persistence_days[_id], "recurrence runs": recurrence_runs[_id], "days to peak": _timing["days_to_peak"] if _timing["days_to_peak"] is not None else "Not applicable (flat)", "first-day peak share": _timing["first_day_peak_share"] if _timing["first_day_peak_share"] is not None else "Not applicable (flat)", "days to return": _timing["days_to_return"] if _timing["days_to_return"] is not None else _missing})
    mo.vstack([mo.md("**Selected pair:** Compare when each path reaches its peak. The two rows give the feature values for these exact paths."), comparison_figure(selected_ids, [f"{shape}<br>ID {_id}" for shape, _id in zip(selected_shapes, selected_ids)]), mo.ui.table(selected_detail_rows, selection=None, page_size=2)])
    return


@app.cell(hide_code=True)
def _(
    clean_feature_definitions,
    collision_pair_readout,
    matched_controls_view,
    mo,
):
    mo.accordion({"Feature definitions and matched controls": mo.vstack([clean_feature_definitions, matched_controls_view, collision_pair_readout])})
    return


@app.cell(hide_code=True)
def _(map_counts, map_shapes, mo):
    _a, _b = map_shapes.index("Step that holds"), map_shapes.index("Gradual rise that holds")
    _c, _d = map_shapes.index("Gradual rise, abrupt reversal"), map_shapes.index("Abrupt rise, gradual recovery")
    collision_pair_readout = mo.md(f"""**Batch readout** — counts are three features; plus days to peak; plus first-day share; plus days to return:

    - **Hold pair:** {map_counts['Three-feature diagnostic'][_a][_b]}/7; {map_counts['Three features + days to peak'][_a][_b]}/7; {map_counts['Three features + first-day peak share'][_a][_b]}/7; {map_counts['Three features + days to return'][_a][_b]}/7. Both returns are unobserved, not evidence of equality or difference.
    - **Time-reversed pair:** {map_counts['Three-feature diagnostic'][_c][_d]}/7; {map_counts['Three features + days to peak'][_c][_d]}/7; {map_counts['Three features + first-day peak share'][_c][_d]}/7; {map_counts['Three features + days to return'][_c][_d]}/7.

    For these pairs, neither days to peak nor first-day share adds clean discrimination beyond the other.""")
    return (collision_pair_readout,)


@app.cell(hide_code=True)
def _(cohort_distances, history_index, weekdays):
    weekday_checks = []
    for _day in weekdays:
        _anchor = history_index[("One-day spike (150)", _day)]
        _shifts = [(other, cohort_distances[_anchor][history_index[("One-day spike (150)", other)]]) for other in weekdays if other != _day]
        _farthest = max(distance for _, distance in _shifts)
        _duration = cohort_distances[_anchor][history_index[("Two-day plateau", _day)]]
        weekday_checks.append({"onset weekday": _day, "farthest weekdays (ties)": ", ".join(day for day, distance in _shifts if distance == _farthest), "farthest_shift": _farthest, "duration_change": _duration, "margin": _duration - _farthest})
    smallest_margin = min(row["margin"] for row in weekday_checks)
    minimum_weekdays = [row["onset weekday"] for row in weekday_checks if row["margin"] == smallest_margin]
    weekday_pass = all(row["margin"] > 0 for row in weekday_checks)
    return minimum_weekdays, smallest_margin, weekday_checks, weekday_pass


@app.cell(hide_code=True)
def _(
    cohort_distances,
    history_index,
    minimum_weekdays,
    mo,
    persistence_days,
    recurrence_runs,
    smallest_margin,
    weekday_checks,
    weekday_pass,
    weekdays,
):
    _sat = history_index[("One-day spike (150)", "Saturday")]
    _fri = history_index[("One-day spike (150)", "Friday")]
    _plateau = history_index[("Two-day plateau", "Saturday")]
    _repeat = history_index[("Two distinct spikes", "Saturday")]
    _shift_ids = [history_index[("One-day spike (150)", day)] for day in weekdays if day != "Saturday"]
    _shift_runs = [abs(recurrence_runs[_sat] - recurrence_runs[i]) for i in _shift_ids]
    weekday_evidence_view = mo.vstack([mo.md(f"""### Full-space weekday check

    From Saturday's 150 spike: Friday's shifted spike distance **{cohort_distances[_sat][_fri]:.6f}**; same-Saturday plateau distance **{cohort_distances[_sat][_plateau]:.6f}**. All seven anchor margins must be strictly positive. Overall: **{'pass' if weekday_pass else 'fail'}**; smallest margin **{smallest_margin:.6f}**, attained by {', '.join(minimum_weekdays)}.

    For context, in the unscaled persistence-only check each shifted single has distance {abs(persistence_days[_sat] - persistence_days[_fri])} days and the Saturday plateau {abs(persistence_days[_sat] - persistence_days[_plateau])} day. Within equal peak and persistence, the six shifted singles have recurrence distances {', '.join(str(x) for x in _shift_runs)} runs versus {abs(recurrence_runs[_sat] - recurrence_runs[_repeat])} run for the Saturday repeated path. These scoped comparisons are not the full-space distance above."""), mo.ui.table(weekday_checks, selection=None, page_size=7)])
    return (weekday_evidence_view,)


@app.cell(hide_code=True)
def _(best_ward_k, mo, ward_summary):
    _silhouette = next(row["silhouette"] for row in ward_summary if row["k"] == best_ward_k)
    mo.md(f"""## Ward and projections

    Ward, neighbors, PCA and UMAP use the same four standardized price-only features over **71 clean histories**. Shape and onset labels are for evaluation only. Ward starts at **k={best_ward_k}** (silhouette **{_silhouette:.3f}**, highest over k=2–12), not a validated taxonomy. Changing k recolors the projections; it does not refit them.""")
    return


@app.cell(hide_code=True)
def _(prepared_feature_rows):
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    ward_labels_by_k = {k: tuple(int(label) for label in AgglomerativeClustering(n_clusters=k, linkage="ward", metric="euclidean").fit_predict(prepared_feature_rows)) for k in range(2, 13)}
    ward_scores = {k: float(silhouette_score(prepared_feature_rows, labels, metric="euclidean")) for k, labels in ward_labels_by_k.items()}
    ward_summary = [{"k": k, "silhouette": ward_scores[k], "cluster sizes": ", ".join(f"{label}: {labels.count(label)}" for label in sorted(set(labels)))} for k, labels in ward_labels_by_k.items()]
    best_ward_k = max(ward_scores, key=ward_scores.get)
    return best_ward_k, ward_labels_by_k, ward_summary


@app.cell(hide_code=True)
def _(mo, ward_summary):
    ward_sweep_view = mo.ui.table(ward_summary, selection=None, page_size=11)
    return (ward_sweep_view,)


@app.cell(hide_code=True)
def _(best_ward_k, mo, ward_labels_by_k):
    cluster_k = mo.ui.dropdown({str(k): k for k in ward_labels_by_k}, value=str(best_ward_k), label="Browse Ward k")
    cluster_k
    return (cluster_k,)


@app.cell(hide_code=True)
def _(cluster_k, history_index, mo, templates, ward_labels_by_k, weekdays):
    selected_cluster_labels = ward_labels_by_k[cluster_k.value]
    assignment_rows = [{"shape": shape, **{day: (f"{selected_cluster_labels[history_index[(shape, day)]]} (ID {history_index[(shape, day)]})" if shape != "Flat reference" else "—") for day in weekdays}, "flat control": (f"{selected_cluster_labels[history_index[(shape, None)]]} (ID {history_index[(shape, None)]})" if shape == "Flat reference" else "—")} for shape in [*templates, "Flat reference"]]
    ward_assignments_view = mo.vstack([mo.md(f"### Assignments at k={cluster_k.value}. Each entry shows cluster label and stable history ID; the flat control has no onset."), mo.ui.table(assignment_rows, selection=None, page_size=12)])
    return selected_cluster_labels, ward_assignments_view


@app.cell(hide_code=True)
def _(cluster_k, history_index, mo, selected_cluster_labels, templates):
    _sat = history_index[("One-day spike (150)", "Saturday")]
    _sat_cluster = selected_cluster_labels[_sat]
    _shared = [shape for shape in templates if selected_cluster_labels[history_index[(shape, "Saturday")]] == _sat_cluster]
    mo.md(f"At k={cluster_k.value}, the Saturday 150 spike shares a cluster with: {', '.join(label for label in _shared if label != 'One-day spike (150)') or 'no other Saturday shape'}.")
    return


@app.cell(hide_code=True)
def _(mo):
    projection_tab = mo.ui.tabs({"PCA": "", "UMAP": ""}, value="PCA", label="Projection")
    projection_tab
    return (projection_tab,)


@app.cell(hide_code=True)
def _(
    cohort_distances,
    day_middle,
    evaluation_metadata,
    history_index,
    peak_displacements,
    persistence_days,
    price_histories,
    recurrence_runs,
    selected_cluster_labels,
    shape_middle,
    timing_candidates,
):
    query_id = history_index[(shape_middle.value, None if shape_middle.value == "Flat reference" else day_middle.value)]
    ranked_peer_ids = sorted((history_id for history_id in range(len(price_histories)) if history_id != query_id), key=lambda history_id: cohort_distances[query_id][history_id])
    neighbor_cutoff = cohort_distances[query_id][ranked_peer_ids[4]]
    neighbor_ids = [history_id for history_id in ranked_peer_ids if cohort_distances[query_id][history_id] <= neighbor_cutoff]
    neighbor_rows = [{"rank": 1 + sum(cohort_distances[query_id][other] < cohort_distances[query_id][history_id] for other in ranked_peer_ids), "history ID": history_id, "distance": cohort_distances[query_id][history_id], "cluster": int(selected_cluster_labels[history_id]), "shape": evaluation_metadata[history_id]["shape"], "weekday": evaluation_metadata[history_id]["weekday"] or "—", "signed peak": peak_displacements[history_id], "persistence days": persistence_days[history_id], "recurrence runs": recurrence_runs[history_id], "observed days to peak": timing_candidates[history_id]["days_to_peak"] if timing_candidates[history_id]["days_to_peak"] is not None else "N/A"} for history_id in neighbor_ids]
    return neighbor_ids, neighbor_rows, query_id, ranked_peer_ids


@app.cell(hide_code=True)
def _(
    cluster_k,
    cohort_distances,
    comparison_figure,
    history_index,
    mo,
    neighbor_ids,
    neighbor_rows,
    query_id,
    ranked_peer_ids,
):
    _neighbor = neighbor_ids[0]
    _closest = cohort_distances[query_id][_neighbor]
    _closest_count = sum(cohort_distances[query_id][history_id] == _closest for history_id in ranked_peer_ids)
    _sat = history_index[("One-day spike (150)", "Saturday")]
    _plateau = history_index[("Two-day plateau", "Saturday")]
    _spike125 = history_index[("One-day spike (125)", "Saturday")]
    _plateau_distance = cohort_distances[_sat][_plateau]
    _smaller_distance = cohort_distances[_sat][_spike125]
    _order = "closer" if _plateau_distance < _smaller_distance else "farther" if _plateau_distance > _smaller_distance else "tied"
    _labels = [f"Selected ID {query_id}", f"One closest ID {_neighbor}"]
    clean_neighbors_view = mo.vstack([mo.md(f"""### Nearest neighbors of the middle gallery path

    Left is the middle gallery selection (ID {query_id}); right is one closest peer in four-feature space, not a unique winner. **{_closest_count}** paths share the nearest distance **{_closest:.6f}**. The table excludes the query and includes five positions plus all ties at the cutoff. Cluster labels reflect Ward k={cluster_k.value}.

    For the Saturday 150 spike, the same-onset plateau ({_plateau_distance:.6f}) is {_order} than the Saturday 125 spike ({_smaller_distance:.6f}); this was a diagnostic, not a tuning objective."""), comparison_figure([query_id, _neighbor], _labels), mo.ui.table(neighbor_rows, selection=None, page_size=10)])
    return (clean_neighbors_view,)


@app.cell(hide_code=True)
def _(
    cluster_k,
    evaluation_metadata,
    go,
    history_index,
    mo,
    pca_coordinates,
    pca_variance_ratios,
    projection_tab,
    selected_cluster_labels,
    umap_coordinates,
):
    _palette = ["#636EFA", "#EF553B", "#00A889", "#AB63FA", "#FFA15A", "#19A9C5", "#E66AB0", "#697E25", "#A56E3A", "#2E91E5", "#D14B70", "#7A60AA"]
    _opening = [("Friday spike", history_index[("One-day spike (150)", "Friday")]), ("Saturday spike", history_index[("One-day spike (150)", "Saturday")]), ("Saturday plateau", history_index[("Two-day plateau", "Saturday")])]
    _projection_figures = []
    for _name, _coordinates in [("PCA", pca_coordinates), ("UMAP", umap_coordinates)]:
        _figure = go.Figure()
        for _cluster in sorted(set(selected_cluster_labels)):
            _groups = {}
            for _id, _point in enumerate(_coordinates):
                if selected_cluster_labels[_id] == _cluster:
                    _groups.setdefault((float(_point[0]), float(_point[1])), []).append(_id)
            _hover = ["<br>".join(f"ID {item}: {evaluation_metadata[item]['shape']} · {evaluation_metadata[item]['weekday'] or 'no onset'} · cluster {_cluster}" for item in ids) for ids in _groups.values()]
            _figure.add_trace(go.Scatter(x=[point[0] for point in _groups], y=[point[1] for point in _groups], mode="markers", name=f"Cluster {_cluster}", marker={"color": _palette[_cluster % len(_palette)], "size": 10, "opacity": 0.8}, customdata=_hover, hovertemplate="%{customdata}<extra></extra>"))
        for _index, (_label, _id) in enumerate(_opening):
            _figure.add_annotation(x=float(_coordinates[_id][0]), y=float(_coordinates[_id][1]), text=f"{_label} · ID {_id}", showarrow=True, ax=[-80, 70, 75][_index], ay=[-55, -75, 55][_index], arrowhead=2, bgcolor="rgba(255,255,255,0.85)", font={"size": 10})
        _figure.update_layout(title=f"{_name} · Ward k={cluster_k.value}", xaxis_title=f"{_name} 1", yaxis_title=f"{_name} 2", template="plotly_white", height=440, margin={"t": 55, "b": 45})
        _projection_figures.append(_figure)
    _captions = {
        "PCA": f"Friday and Saturday spikes coincide; the plateau sits nearby. At the default Ward cut they share a color. Axes explain {pca_variance_ratios[0]:.1%} and {pca_variance_ratios[1]:.1%} of variance.",
        "UMAP": "Find the same labeled spikes: UMAP separates these identical input rows. Use full-space distances, not plotted gaps, to judge neighbors.",
    }
    mo.vstack([mo.md(_captions[projection_tab.value]), _projection_figures[0 if projection_tab.value == "PCA" else 1]])
    return


@app.cell(hide_code=True)
def _(mo, projection_coordinates_view, ward_assignments_view, ward_sweep_view):
    mo.accordion({"Ward sweep, assignments and projection settings": mo.vstack([
        mo.md("UMAP uses two components, 15 neighbors, minimum distance 0.1, Euclidean distance, seed 42 and one worker, with `compatibility_layout=True` to preserve the original layout. Hover points for stable IDs and Ward labels; projected overlaps share a hover entry. The cluster labels are arbitrary and can change with k."),
        ward_sweep_view, ward_assignments_view, projection_coordinates_view,
    ])})
    return


@app.cell(hide_code=True)
def _(
    band_settings_view,
    earlier_peak_correction_details,
    earlier_peak_correction_summary,
    mo,
    shape_split_failure_view,
    shape_split_scores_view,
):
    mo.vstack([
        mo.md("## Supporting detail"),
        mo.accordion({"Shape-only scores: typical and stress": shape_split_scores_view,
                      "Why reversal and size equivalence failed: counts and seed traces": shape_split_failure_view}, multiple=True),
        mo.accordion({"Earlier settings and peak-correction evidence": mo.vstack([
            band_settings_view, earlier_peak_correction_summary, earlier_peak_correction_details,
        ])}),
    ])
    return


@app.cell(hide_code=True)
def _(
    holdout_bootstrap_n,
    holdout_bootstrap_seed,
    holdout_clean_checks,
    holdout_margin_differences,
    holdout_neighbors,
    holdout_rate_differences,
    holdout_replay,
    holdout_scores,
    mo,
    weak_spike_onsets,
):
    _rows = []
    for (_level, _base, _method), _scores in holdout_scores.items():
        if _base != 100:
            continue
        _total = len(_scores)
        _spikes = _total * len(weak_spike_onsets)
        _flat = sum(row["flat any run"] for row in _scores)
        _hits = sum(row["spike hits"] for row in _scores)
        _pass = sum(row["weekday margin"] > 0 for row in _scores)
        _rows.append({
            "noise": _level, "rule": _method, "flat paths with a run": f"{_flat}/{_total} ({_flat / _total:.1%})",
            "10% spike-day recall": f"{_hits}/{_spikes} ({_hits / _spikes:.1%})",
            "all-seven weekday pass": f"{_pass}/{_total} ({_pass / _total:.1%})",
            "worst weekday margin": f"{min(row['weekday margin'] for row in _scores):+.3f}",
        })
    _deltas = [{"noise": row["noise"], "metric": row["metric"],
               "change (pp)": f"{100 * row['change']:+.1f}",
               "95% interval (pp)": f"[{100 * row['95% low']:+.1f}, {100 * row['95% high']:+.1f}]"}
               for row in holdout_rate_differences]
    _median_summary = "; ".join(f"{level} {change:+.3f}" for level, change in holdout_margin_differences.items())
    mo.accordion({"Holdout detail": mo.vstack([
        mo.md("Absolute results below use one flat and seven spike days per seed. The worst margin is the smallest observed gap between the same-onset plateau distance and the farthest shifted spike distance."),
        mo.ui.table(_rows, selection=None, page_size=4, show_search=False),
        mo.md(f"**Paired changes (median-5 minus first-price).** 95% percentile intervals resample the whole seed {holdout_bootstrap_n:,} times (resampling seed {holdout_bootstrap_seed}). Median paired change in the per-seed minimum margin: {_median_summary}."),
        mo.ui.table(_deltas, selection=None, page_size=6, show_search=False),
        mo.accordion({"Clean checks and proportional replay": mo.vstack([
            mo.ui.table(holdout_clean_checks, selection=None, page_size=6),
            mo.ui.table(holdout_replay, selection=None, page_size=8),
        ]), "Neighbor example · typical / base 100 / seed 64": mo.vstack([
            mo.md("Saturday 150 spike; five positions plus cutoff ties in full standardized feature space. This is the first holdout seed, not a representative sample."),
            mo.ui.table(holdout_neighbors, selection=None, page_size=10),
        ])}, multiple=True),
    ])})
    return


@app.cell(hide_code=True)
def _(
    feature_drift_view,
    first_price_development_view,
    generator_calibration_view,
    median_opening_development_view,
    mo,
    proportional_replay_view,
    untuned_neighbors_view,
):
    mo.accordion({"Development sweeps and simulator details": mo.accordion({
        "Noise calibration and exact-baseline failure": mo.vstack([generator_calibration_view, feature_drift_view, untuned_neighbors_view]),
        "Clean proportional replay": proportional_replay_view,
        "Fixed-band development sweep": first_price_development_view,
        "Median-of-five development comparison": median_opening_development_view,
    }, multiple=True)})
    return


@app.cell(hide_code=True)
def _(
    band_development_scores,
    describe_locked_band,
    dist,
    excursion_weekday_margin,
    history_index,
    holdout_widths,
    median,
    noise_histories,
    opening_development_scores,
    prepared_feature_rows,
    standardized_excursion_rows,
    weekdays,
):
    weekday_shift_ids = tuple(history_index[("One-day spike (150)", day)] for day in weekdays)
    weekday_plateau_ids = tuple(history_index[("Two-day plateau", day)] for day in weekdays)


    def worst_weekday_contrast(rows):
        pairs = []
        for anchor, plateau in zip(weekday_shift_ids, weekday_plateau_ids, strict=True):
            shift = max((other for other in weekday_shift_ids if other != anchor),
                        key=lambda other: dist(rows[anchor], rows[other]))
            shift_distance = dist(rows[anchor], rows[shift])
            plateau_distance = dist(rows[anchor], rows[plateau])
            gap_components = tuple((a - p) ** 2 - (a - s) ** 2
                                   for a, p, s in zip(rows[anchor], rows[plateau], rows[shift], strict=True))
            pairs.append((plateau_distance - shift_distance, anchor, plateau, shift, gap_components))
        return min(pairs, key=lambda pair: pair[0])


    weekday_attribution_features = ("Signed peak", "Persistence", "Recurrence", "Days to peak")
    weekday_failure_details = []
    weekday_ablation_rows = []
    weekday_gap_rows = []
    for _level in ("typical", "stress"):
        for _rule, _width in holdout_widths.items():
            _passes = 0
            _repaired = [0] * 5
            _broken = [0] * 5
            _failures = []
            for _seed, _paths in noise_histories[_level][100].items():
                _rows = standardized_excursion_rows(tuple(describe_locked_band(path, _rule, _width) for path in _paths))
                _margin, _anchor, _plateau, _shift, _components = worst_weekday_contrast(_rows)
                _passes += _margin > 0
                if _margin <= 0:
                    _record = {"noise": _level, "rule": _rule, "seed": _seed, "margin": _margin,
                               "anchor ID": _anchor, "same-onset plateau ID": _plateau, "farthest shift ID": _shift,
                               "components": _components}
                    _failures.append(_record)
                    weekday_failure_details.append(_record)
                for _i, _columns in enumerate(((0,), (1,), (2,), (3,), (1, 2, 3))):
                    _hybrid = tuple(tuple(clean[col] if col in _columns else row[col] for col in range(len(row)))
                                    for row, clean in zip(_rows, prepared_feature_rows, strict=True))
                    _restored_pass = excursion_weekday_margin(_hybrid) > 0
                    _repaired[_i] += _margin <= 0 and _restored_pass
                    _broken[_i] += _margin > 0 and not _restored_pass
            for _i, _label in enumerate((*weekday_attribution_features, "All run features")):
                weekday_ablation_rows.append({"noise": _level, "rule": _rule, "restored clean coordinate": _label,
                                             "original pass / 64": _passes, "failed → pass": _repaired[_i],
                                             "pass → failed": _broken[_i],
                                             "pass after restoration / 64": _passes + _repaired[_i] - _broken[_i]})
            for _col, _label in enumerate(weekday_attribution_features):
                _values = [row["components"][_col] for row in _failures]
                weekday_gap_rows.append({"noise": _level, "rule": _rule, "feature": _label,
                                         "failed draws": len(_values), "negative contribution": sum(x < 0 for x in _values),
                                         "median squared-gap contribution": round(median(_values), 6) if _values else None})

    weekday_pair_counts = []
    for _level in ("typical", "stress"):
        _first = band_development_scores["Flat p90", _level, 100]
        _median = opening_development_scores["Flat p90", _level, 100]
        _pairs = [(a["weekday margin"] > 0, b["weekday margin"] > 0) for a, b in zip(_first, _median, strict=True)]
        weekday_pair_counts.append({"noise": _level, "both pass": _pairs.count((True, True)),
                                    "first only": _pairs.count((True, False)), "median-5 only": _pairs.count((False, True)),
                                    "neither passes": _pairs.count((False, False))})
    return (
        weekday_ablation_rows,
        weekday_attribution_features,
        weekday_failure_details,
        weekday_gap_rows,
        weekday_pair_counts,
        weekday_plateau_ids,
        weekday_shift_ids,
    )


@app.cell(hide_code=True)
def _(
    mo,
    weekday_ablation_rows,
    weekday_attribution_features,
    weekday_failure_details,
    weekday_gap_rows,
    weekday_pair_counts,
):
    _main = [row for row in weekday_ablation_rows if row["rule"] == "Median-5 p90"]
    _failure = next(row for row in weekday_failure_details if row["noise"] == "typical" and row["rule"] == "Median-5 p90")
    _example = [{"feature": label, "squared-gap contribution": round(value, 6)}
                for label, value in zip(weekday_attribution_features, _failure["components"], strict=True)]
    peak_restoration_view = mo.vstack([
        mo.md("""## Follow-up: where does the weekday comparison break?

    **Development diagnosis only (seeds 0–63, base 100).** We compare the locked p90 rules on the same seeds. For each failed draw, the worst of the seven anchor margins is broken into four squared-distance contributions: same-onset plateau minus farthest shifted spike. A negative contribution favors the shifted spike being farther away. This measures one duration contrast and is not a detector.

    The clean-coordinate restoration asks whether replacing a measured coordinate with its matched synthetic clean value would fix the pass. The closest/farthest partners can change after restoration. These are diagnostic counterfactuals, not deployable features; planted answers never enter the price-only fit."""),
        mo.ui.table(weekday_pair_counts, selection=None, page_size=2, show_search=False),
        mo.ui.table(_main, selection=None, page_size=10, show_search=False),
        mo.accordion({"Both rules, gap contributions and one failed draw": mo.vstack([
            mo.ui.table(weekday_ablation_rows, selection=None, page_size=10),
            mo.ui.table(weekday_gap_rows, selection=None, page_size=8),
            mo.md(f"First failed typical median-5 draw: seed {_failure['seed']}, margin {_failure['margin']:+.6f}. Anchor ID {_failure['anchor ID']}; same-onset plateau ID {_failure['same-onset plateau ID']}; farthest shift ID {_failure['farthest shift ID']}. Contributions sum to the squared-distance gap, not the unsquared margin."),
            mo.ui.table(_example, selection=None, page_size=4),
        ])}),
    ])
    return (peak_restoration_view,)


@app.cell(hide_code=True)
def _(
    dist,
    excursion_flat_id,
    excursion_weekday_margin,
    first_price_logs,
    history_index,
    log,
    median_opening,
    median_opening_features,
    median_opening_upward,
    standardized_excursion_rows,
    weak_spike_onsets,
    weekday_plateau_ids,
    weekday_shift_ids,
    weekdays,
):
    local_peak_weight = 0.25
    local_peak_levels = (110, 125, 150, 80)
    _labels = {**{level: f"One-day spike ({level})" for level in local_peak_levels[:3]}, 80: "One-day dip (80)"}
    local_peak_eval_ids = {level: tuple(history_index[(shape, weekday)] for weekday in weekdays)
                           for level, shape in _labels.items()}
    local_peak_dev_gates = {"protected weekday passes": 42, "magnitude separation passes": 61}


    def local_peak_features(history, width):
        incumbent = median_opening_features(history, width)
        initial_logs = first_price_logs(history)
        peak_day = max(range(len(initial_logs)), key=lambda day: abs(initial_logs[day]))
        opening = median_opening(history)
        if abs(log(history[peak_day] / opening)) <= width:
            return incumbent
        nearby = (log(history[day] / opening) for day in (peak_day - 1, peak_day + 1) if 0 <= day < len(history))
        correction = local_peak_weight * sum(value for value in nearby if abs(value) <= width)
        return (incumbent[0] - correction, *incumbent[1:])


    def protected_weekday_margin(incumbent, candidate):
        return min(min(dist(incumbent[anchor], incumbent[plateau]), dist(candidate[anchor], candidate[plateau]))
                   - max(dist(candidate[anchor], candidate[shift]) for shift in weekday_shift_ids if shift != anchor)
                   for anchor, plateau in zip(weekday_shift_ids, weekday_plateau_ids, strict=True))


    def packed_local_peak_draw(seed, histories, width):
        original = tuple(median_opening_features(path, width) for path in histories)
        updated = tuple(local_peak_features(path, width) for path in histories)
        old_rows = standardized_excursion_rows(original)
        new_rows = standardized_excursion_rows(updated)
        peak_samples = {level: tuple((original[item][0], updated[item][0]) for item in indices)
                        for level, indices in local_peak_eval_ids.items()}
        separation = tuple(all(min(pair[index] for pair in peak_samples[upper])
                               - max(pair[index] for pair in peak_samples[lower]) >= 0.5 * log(upper / lower)
                               for lower, upper in ((110, 125), (125, 150))) for index in (0, 1))
        return {
            "seed": seed, "incumbent margin": excursion_weekday_margin(old_rows),
            "candidate margin": excursion_weekday_margin(new_rows),
            "protected margin": protected_weekday_margin(old_rows, new_rows),
            "both magnitude gaps": separation,
            "negative dips": tuple(sum(pair[index] < 0 for pair in peak_samples[80]) for index in (0, 1)),
            "peak absolute error totals": {level: tuple(sum(abs(pair[index] - log(level / 100)) for pair in samples)
                                                          for index in (0, 1)) for level, samples in peak_samples.items()},
            "run fields unchanged": all(a[1:] == b[1:] for a, b in zip(original, updated, strict=True)),
            "flat any run": updated[excursion_flat_id][1] > 0,
            "spike hits": sum(median_opening_upward(histories[item], day, width) for item, day in weak_spike_onsets),
        }

    return (
        local_peak_dev_gates,
        local_peak_eval_ids,
        local_peak_features,
        local_peak_levels,
        packed_local_peak_draw,
    )


@app.cell(hide_code=True)
def _(
    jitter_seeds,
    local_peak_dev_gates,
    local_peak_features,
    local_peak_levels,
    noise_histories,
    opening_development_scores,
    opening_widths,
    packed_local_peak_draw,
    replay_features,
    replay_histories,
    weekdays,
):
    local_peak_width = opening_widths["Flat p90"]
    local_peak_development = {level: [packed_local_peak_draw(seed, histories, local_peak_width)
                                     for seed, histories in bases[100].items()]
                              for level, bases in noise_histories.items()}
    local_peak_clean = []
    for _base, _histories in replay_histories.items():
        _rows = tuple(local_peak_features(path, local_peak_width) for path in _histories)
        _reference = tuple((*row[:3], row[3]["days_to_peak"]) for row in replay_features[_base])
        local_peak_clean.append({"base": _base, "max absolute peak change": max(abs(row[0] - clean[0]) for row, clean in zip(_rows, _reference, strict=True)),
                                 "run fields and missing timing unchanged": all(row[1:] == clean[1:] for row, clean in zip(_rows, _reference, strict=True))})
    local_peak_clean_preserved = all(row["max absolute peak change"] <= 1e-12 and row["run fields and missing timing unchanged"]
                                     for row in local_peak_clean)


    def summarize_local_peak_draws(rows):
        original = [record["incumbent margin"] > 0 for record in rows]
        candidate = [record["candidate margin"] > 0 for record in rows]
        return {
            "incumbent pass": sum(original), "ordinary pass": sum(candidate),
            "protected pass": sum(row["protected margin"] > 0 for row in rows),
            "ordinary gains": sum(not a and b for a, b in zip(original, candidate, strict=True)),
            "ordinary losses": sum(a and not b for a, b in zip(original, candidate, strict=True)),
            "incumbent magnitude passes": sum(row["both magnitude gaps"][0] for row in rows),
            "candidate magnitude passes": sum(row["both magnitude gaps"][1] for row in rows),
            "incumbent negative dips": sum(row["negative dips"][0] for row in rows),
            "candidate negative dips": sum(row["negative dips"][1] for row in rows),
            "flat runs": sum(row["flat any run"] for row in rows), "spike hits": sum(row["spike hits"] for row in rows),
            "MAE": {level: tuple(sum(row["peak absolute error totals"][level][index] for row in rows)
                                 / (len(rows) * len(weekdays)) for index in (0, 1)) for level in local_peak_levels},
        }


    local_peak_dev_summary = {level: summarize_local_peak_draws(rows) for level, rows in local_peak_development.items()}
    local_peak_isolated = all(updated["run fields unchanged"] and updated["seed"] == old["seed"]
                              and updated["flat any run"] == old["flat any run"] and updated["spike hits"] == old["spike hits"]
                              for level, rows in local_peak_development.items()
                              for updated, old in zip(rows, opening_development_scores["Flat p90", level, 100], strict=True))
    _typical = local_peak_dev_summary["typical"]
    local_peak_dev_checks = {
        "protected weekday passes": _typical["protected pass"] >= local_peak_dev_gates["protected weekday passes"],
        "magnitude separation": _typical["candidate magnitude passes"] >= local_peak_dev_gates["magnitude separation passes"],
        "negative dip sign": _typical["candidate negative dips"] == len(jitter_seeds) * len(weekdays),
        "level-wise amplitude MAE": all(candidate <= incumbent + 1e-12 for incumbent, candidate in _typical["MAE"].values()),
        "clean and run isolation": local_peak_clean_preserved and local_peak_isolated,
    }
    local_peak_advances = all(local_peak_dev_checks.values())
    return (
        local_peak_advances,
        local_peak_clean,
        local_peak_dev_checks,
        local_peak_dev_summary,
        local_peak_development,
        local_peak_isolated,
        local_peak_width,
    )


@app.cell(hide_code=True)
def _(
    local_peak_advances,
    local_peak_clean,
    local_peak_dev_checks,
    local_peak_dev_summary,
    local_peak_isolated,
    local_peak_width,
    mo,
):
    _score = [{"noise": level, "incumbent / 64": row["incumbent pass"],
               "corrected / 64": row["ordinary pass"], "protected / 64": row["protected pass"],
               "paired ordinary gains / losses": f"+{row['ordinary gains']} / -{row['ordinary losses']}",
               "magnitude ordering / 64 · old → new": f"{row['incumbent magnitude passes']} → {row['candidate magnitude passes']}",
               "negative dips / 448 · old → new": f"{row['incumbent negative dips']} → {row['candidate negative dips']}"}
              for level, row in local_peak_dev_summary.items()]
    _mae = [{"noise": level, "planted level": price, "median-5 p90 MAE": round(original, 6),
             "corrected MAE": round(candidate, 6), "change": round(candidate - original, 6)}
            for level, row in local_peak_dev_summary.items() for price, (original, candidate) in row["MAE"].items()]
    _failed = ", ".join(gate for gate, passes in local_peak_dev_checks.items() if not passes) or "none"
    local_peak_correction_view = mo.vstack([
        mo.md(f"""## Follow-up: can adjacent prices improve the signed peak?

    **{'Advances' if local_peak_advances else 'Does not advance'}** from development. Missed gates: **{_failed}**.

    The incumbent is median-5 p90 (log width **{local_peak_width:.6f}**). If its raw signed peak day is outside the band, subtract **one quarter** of the sum of its immediate *in-band* neighbors’ log departures from the median-5 reference. Out-of-band neighbors and missing neighbors contribute zero. The peak day, run features and clean feature scaling stay fixed.

    **What counts as a win:** In typical jitter (seeds 0–63), require ≥42/64 weekday passes with the plateau distance capped at its incumbent value, so moving plateaus farther away earns no credit. Require both 125-over-110 and 150-over-125 ranges to clear half their clean log gap across all weekday shifts on ≥61/64 seeds, all 448 dips to stay negative, no increase in peak MAE at any of the four levels, and unchanged clean rows, run flags and weak-spike hits. Stress is a separate readout."""),
        mo.ui.table(_score, selection=None, page_size=2, show_search=False),
        mo.accordion({"Level-wise peak errors and isolation checks": mo.vstack([
            mo.md("Peak MAE is in log units against the planted signed displacement. Planted levels are evaluation targets only."),
            mo.ui.table(_mae, selection=None, page_size=8),
            mo.ui.table(local_peak_clean, selection=None, page_size=3),
            mo.md(f"Run features and detector scoring unchanged on both development levels: **{local_peak_isolated}**."),
        ])}),
    ])
    return (local_peak_correction_view,)


@app.cell(hide_code=True)
def _(
    dist,
    local_peak_development,
    local_peak_features,
    local_peak_width,
    median,
    median_opening_features,
    noise_histories,
    standardized_excursion_rows,
    weekday_plateau_ids,
    weekday_shift_ids,
    weekdays,
):
    local_peak_weekday_trace = []
    for _seed, _paths in noise_histories["typical"][100].items():
        _old = standardized_excursion_rows(tuple(median_opening_features(path, local_peak_width) for path in _paths))
        _new = standardized_excursion_rows(tuple(local_peak_features(path, local_peak_width) for path in _paths))
        _anchor_margins = []
        for _anchor, _plateau in zip(weekday_shift_ids, weekday_plateau_ids, strict=True):
            _p_old = dist(_old[_anchor], _old[_plateau])
            _p_new = dist(_new[_anchor], _new[_plateau])
            _s_old = max(dist(_old[_anchor], _old[peer]) for peer in weekday_shift_ids if peer != _anchor)
            _s_new = max(dist(_new[_anchor], _new[peer]) for peer in weekday_shift_ids if peer != _anchor)
            _anchor_margins.append((_p_old - _s_old, _p_old - _s_new, min(_p_old, _p_new) - _s_new))
        _a, _b, _c = map(min, zip(*_anchor_margins, strict=True))
        _record = local_peak_development["typical"][_seed]
        _old_error, _new_error = _record["peak absolute error totals"][150]
        assert _a == _record["incumbent margin"] and _c == _record["protected margin"]
        local_peak_weekday_trace.append({"seed": _seed, "150-spike MAE change": (_new_error - _old_error) / len(weekdays),
                                         "A incumbent": _a, "B shift-only accounting": _b, "C protected": _c})

    local_peak_trace_summary = []
    for _before, _after in ((True, True), (True, False), (False, True), (False, False)):
        _rows = [row for row in local_peak_weekday_trace if (row["A incumbent"] > 0, row["C protected"] > 0) == (_before, _after)]
        local_peak_trace_summary.append({
            "incumbent → protected": f"{'Pass' if _before else 'Fail'} → {'pass' if _after else 'fail'}",
            "seeds": len(_rows), "lower 150-spike MAE": sum(row["150-spike MAE change"] < 0 for row in _rows),
            "median B − A": median(row["B shift-only accounting"] - row["A incumbent"] for row in _rows) if _rows else None,
            "median C − B": median(row["C protected"] - row["B shift-only accounting"] for row in _rows) if _rows else None,
            "pass at B": sum(row["B shift-only accounting"] > 0 for row in _rows),
        })
    return local_peak_trace_summary, local_peak_weekday_trace


@app.cell(hide_code=True)
def _(local_peak_trace_summary, local_peak_weekday_trace, mo):
    _retained, _lost, _gained, _persistent = local_peak_trace_summary
    _b_passes = sum(row["pass at B"] for row in local_peak_trace_summary)
    _b_removed = _lost["pass at B"] + _persistent["pass at B"]
    _median_shift = _persistent["median B − A"]
    paired_weekday_margins_view = mo.vstack([
        mo.md(f"""## Follow-up: why did lower peak error not improve weekday passes?

    **Lower error often did not change the decision.** Of the **{_persistent['seeds']}** seeds that failed both the incumbent and protected check, **{_persistent['lower 150-spike MAE']}** had lower mean absolute error across their seven planted 150 spikes. This is a paired development diagnosis (typical jitter, seeds 0–63, base 100), not a new detector or holdout.

    For each seed, each margin takes the worst of all seven anchors; strictly positive means pass. **A** is incumbent plateau distance minus incumbent farthest-shift distance. **B** keeps the incumbent plateau distance but uses the corrected farthest-shift distance. **C** also lets a corrected plateau come closer, but never gives credit for pushing it farther away. Recompute the farthest shift in each representation; the worst anchor can change too."""),
        mo.ui.table(local_peak_trace_summary, selection=None, page_size=4, show_search=False,
                    format_mapping={"median B − A": "{:+.4f}".format, "median C − B": "{:+.4f}".format}),
        mo.md(f"Among persistent failures, the median change from shifted-spike distances alone was **{_median_shift:+.4f}** standardized distance units; **{_persistent['pass at B']}** crossed zero at B. Overall, B would pass **{_b_passes}/64**; allowing plateaus to come closer removed **{_b_removed}** of those passes, leaving **{_retained['seeds'] + _gained['seeds']}/64** at C. B is an accounting step, not a candidate score."),
        mo.accordion({"Paired per-seed margins": mo.ui.table(local_peak_weekday_trace, selection=None, page_size=10)}),
    ])
    return (paired_weekday_margins_view,)


@app.cell(hide_code=True)
def _(
    dist,
    excursion_flat_id,
    feature_scales,
    first_price_logs,
    history_index,
    holdout_seeds,
    jitter_seeds,
    local_peak_eval_ids,
    log,
    median_opening,
    median_opening_features,
    median_opening_upward,
    opening_widths,
    standardized_excursion_rows,
    templates,
    timing_fill,
    weak_spike_onsets,
    weekdays,
):
    shape_split_width = opening_widths["Flat p90"]
    shape_split_methods = ("Four-feature benchmark", "Shape-only")
    shape_split_contrasts = ("Duration", "Recurrence", "Reversal")
    shape_split_gates = {"duration": 42, "duration net gain": 7, "recurrence": 48, "reversal": 48,
                         "size equivalence": 48, "onsets for size equivalence": 6, "negative dips": 448}
    shape_split_confirmation_seeds = tuple(range(576, 1088))
    shape_split_confirmation_gates = {key: value if key == "onsets for size equivalence" else 8 * value
                                      for key, value in shape_split_gates.items()}
    assert set(shape_split_confirmation_seeds).isdisjoint((*jitter_seeds, *holdout_seeds))

    shape_split_ids = {shape: tuple(history_index[(shape, day)] for day in weekdays) for shape in templates}
    shape_split_specs = (
        ("Duration", "One-day spike (150)", "Two-day plateau", 1, 1),
        ("Recurrence", "One-day spike (150)", "Two distinct spikes", 2, 1),
        ("Reversal", "Gradual rise, abrupt reversal", "Abrupt rise, gradual recovery", 3, 2),
    )


    def shape_split_credit(rows, anchor, contrast, coordinate, cap, direction):
        observed = direction * (rows[contrast][coordinate] - rows[anchor][coordinate])
        return min(observed, cap) / feature_scales[coordinate]


    def shape_split_score(seed, histories):
        features = tuple(median_opening_features(path, shape_split_width) for path in histories)
        rows = tuple((*row[:3], timing_fill if row[3] is None else row[3]) for row in features)
        standardized = standardized_excursion_rows(features)
        coordinates = (standardized, tuple(row[1:] for row in standardized))
        opening = tuple(median_opening(path) for path in histories)
        logs_relative_to_opening = tuple(tuple(log(price / reference) for price in path)
                                         for path, reference in zip(histories, opening, strict=True))
        raw_logs = tuple(first_price_logs(path) for path in histories)
        peak_days = tuple(max(range(len(path)), key=lambda t: abs(path[t])) for path in raw_logs)

        contrasts = {method: {name: [] for name in shape_split_contrasts} for method in shape_split_methods}
        sizes = {method: [] for method in shape_split_methods}
        for onset, day in enumerate(weekdays, start=7):
            index = onset - 7
            for name, left, right, coordinate, cap in shape_split_specs:
                left_id, right_id = shape_split_ids[left][index], shape_split_ids[right][index]
                left_path, right_path = logs_relative_to_opening[left_id], logs_relative_to_opening[right_id]
                if name == "Duration":
                    event = (left_path[onset] > shape_split_width
                             and min(right_path[onset:onset + 2]) > shape_split_width)
                elif name == "Recurrence":
                    event = (min(right_path[onset], right_path[onset + 2]) > shape_split_width
                             and abs(right_path[onset + 1]) <= shape_split_width)
                else:
                    event = all(
                        features[item][3] is not None
                        and peak_days[item] == target
                        for item, target in ((left_id, onset + 2), (right_id, onset))
                    )
                directions = ((left, left_id, right_id, 1),) if name != "Reversal" else (
                    (left, left_id, right_id, -1), (right, right_id, left_id, 1),
                )
                for anchor_shape, anchor, target, sign in directions:
                    credit = shape_split_credit(rows, anchor, target, coordinate, cap, sign)
                    for method, projection in zip(shape_split_methods, coordinates, strict=True):
                        within = max(dist(projection[anchor], projection[peer])
                                     for peer in shape_split_ids[anchor_shape] if peer != anchor)
                        contrasts[method][name].append({
                            "weekday": day, "anchor": anchor, "contrast": target, "event observed": event,
                            "within distance": within, "intended credit": credit,
                            "ordinary margin": dist(projection[anchor], projection[target]) - within,
                            "protected margin": credit - within,
                        })

            size_ids = tuple(local_peak_eval_ids[level][index] for level in (110, 125, 150))
            detected = tuple(logs_relative_to_opening[item][onset] > shape_split_width for item in size_ids)
            for method, projection in zip(shape_split_methods, coordinates, strict=True):
                a, b, c = (projection[item] for item in size_ids)
                maximum = max(dist(a, b), dist(a, c), dist(b, c))
                sizes[method].append({"weekday": day, "all detected": all(detected), "detected 110/125/150": detected,
                                      "max size distance": maximum, "size margin": 0.5 / feature_scales[1] - maximum})

        peaks = {level: tuple(features[item][0] for item in ids) for level, ids in local_peak_eval_ids.items()}
        return {
            "seed": seed, "contrasts": contrasts, "size checks": sizes, "raw peaks": peaks,
            "flat run": features[excursion_flat_id][1] > 0,
            "spike hits": sum(median_opening_upward(histories[item], day, shape_split_width) for item, day in weak_spike_onsets),
            "same extracted values": all(row[1:] == sliced for row, sliced in zip(*coordinates, strict=True))
                                     and all(row[0] == values[day] for row, values, day in zip(features, raw_logs, peak_days, strict=True)),
        }


    def shape_split_pass(record, method, contrast, protected, minimum_onsets):
        if contrast == "Size equivalence":
            return sum(item["all detected"] and item["size margin"] > 0 for item in record["size checks"][method]) >= minimum_onsets
        anchors = record["contrasts"][method][contrast]
        if protected:
            return all(item["event observed"] and item["protected margin"] > 0 for item in anchors)
        return all(item["ordinary margin"] > 0 for item in anchors)

    return (
        shape_split_contrasts,
        shape_split_gates,
        shape_split_ids,
        shape_split_methods,
        shape_split_pass,
        shape_split_score,
        shape_split_width,
    )


@app.cell(hide_code=True)
def _(
    local_peak_eval_ids,
    log,
    median,
    shape_split_contrasts,
    shape_split_methods,
    shape_split_pass,
    weekdays,
):
    shape_split_tests = (*shape_split_contrasts, "Size equivalence")


    def shape_split_comparison(records, minimum_onsets):
        benchmark, candidate = shape_split_methods
        summary = []
        for contrast in shape_split_tests:
            is_size = contrast == "Size equivalence"
            by_method = {}
            for method in shape_split_methods:
                if is_size:
                    margins = [sorted((row["size margin"] for row in draw["size checks"][method]), reverse=True)[minimum_onsets - 1]
                               for draw in records]
                    all_onsets = sum(shape_split_pass(draw, method, contrast, True, len(weekdays)) for draw in records)
                    ordinary = None
                    ordinary_margins = None
                else:
                    margins = [min(row["protected margin"] for row in draw["contrasts"][method][contrast]) for draw in records]
                    ordinary_margins = median(min(row["ordinary margin"] for row in draw["contrasts"][method][contrast]) for draw in records)
                    all_onsets = None
                    ordinary = sum(shape_split_pass(draw, method, contrast, False, minimum_onsets) for draw in records)
                by_method[method] = {
                    "passes": [shape_split_pass(draw, method, contrast, True, minimum_onsets) for draw in records],
                    "ordinary": ordinary, "all size onsets": all_onsets,
                    "median margin": median(margins), "ordinary median margin": ordinary_margins,
                }
            first, second = by_method[benchmark], by_method[candidate]
            paired = list(zip(first["passes"], second["passes"], strict=True))
            summary.append({
                "contrast": contrast, "benchmark passes": sum(first["passes"]), "shape-only passes": sum(second["passes"]),
                "gained": sum(not a and b for a, b in paired), "lost": sum(a and not b for a, b in paired),
                "benchmark ordinary": first["ordinary"], "shape-only ordinary": second["ordinary"],
                "benchmark all size onsets": first["all size onsets"], "shape-only all size onsets": second["all size onsets"],
                "benchmark median margin": first["median margin"], "shape-only median margin": second["median margin"],
                "benchmark ordinary median margin": first["ordinary median margin"],
                "shape-only ordinary median margin": second["ordinary median margin"],
            })
        return summary


    def shape_split_magnitude(records):
        return {
            "MAE": {level: sum(abs(value - log(level / 100)) for row in records for value in row["raw peaks"][level])
                    / (len(records) * len(weekdays)) for level in local_peak_eval_ids},
            "negative dips": sum(value < 0 for row in records for value in row["raw peaks"][80]),
            "both size gaps": sum(all(min(row["raw peaks"][upper]) - max(row["raw peaks"][lower]) >= 0.5 * log(upper / lower)
                                      for lower, upper in ((110, 125), (125, 150))) for row in records),
            "flat runs": sum(row["flat run"] for row in records), "weak spike hits": sum(row["spike hits"] for row in records),
        }


    def assess_shape_split(comparison, magnitude, gates, clean_preserved, shared_extraction):
        duration, recurrence, reversal, equivalence = comparison
        return {
            "Duration target": duration["shape-only passes"] >= gates["duration"],
            "Duration gain vs ordinary benchmark": duration["shape-only passes"] - duration["benchmark ordinary"] >= gates["duration net gain"],
            "Recurrence": recurrence["shape-only passes"] >= gates["recurrence"],
            "Reversal": reversal["shape-only passes"] >= gates["reversal"],
            "Size equivalence": equivalence["shape-only passes"] >= gates["size equivalence"],
            "Negative dip sign": magnitude["negative dips"] == gates["negative dips"],
            "Clean replay and shared extraction": clean_preserved and shared_extraction,
        }

    return (
        assess_shape_split,
        shape_split_comparison,
        shape_split_magnitude,
        shape_split_tests,
    )


@app.cell(hide_code=True)
def _(
    assess_shape_split,
    noise_histories,
    opening_development_scores,
    replay_histories,
    shape_split_comparison,
    shape_split_gates,
    shape_split_magnitude,
    shape_split_methods,
    shape_split_pass,
    shape_split_score,
    shape_split_tests,
    weekdays,
):
    _benchmark, _candidate = shape_split_methods
    shape_split_clean_checks = []
    for _base, _histories in replay_histories.items():
        _clean = shape_split_score(None, _histories)
        shape_split_clean_checks.append({
            "base": _base, "size distance zero": all(item["max size distance"] == 0 for item in _clean["size checks"][_candidate]),
            "all contrast events and margins pass": all(shape_split_pass(_clean, _candidate, contrast, True, len(weekdays))
                                                        for contrast in shape_split_tests),
            "shared extraction and clean run checks": _clean["same extracted values"] and not _clean["flat run"] and _clean["spike hits"] == 7,
        })
    shape_split_clean_preserved = all(all(value for key, value in row.items() if key != "base") for row in shape_split_clean_checks)

    shape_split_development = {level: [shape_split_score(seed, draw) for seed, draw in bases[100].items()]
                               for level, bases in noise_histories.items()}
    shape_split_dev_comparison = {level: shape_split_comparison(rows, shape_split_gates["onsets for size equivalence"])
                                  for level, rows in shape_split_development.items()}
    shape_split_dev_magnitude = {level: shape_split_magnitude(rows) for level, rows in shape_split_development.items()}
    shape_split_dev_shared = all(draw["same extracted values"] and draw["seed"] == old["seed"]
                                 and draw["flat run"] == old["flat any run"] and draw["spike hits"] == old["spike hits"]
                                 and shape_split_pass(draw, _benchmark, "Duration", False, 7) == (old["weekday margin"] > 0)
                                 for level, draws in shape_split_development.items()
                                 for draw, old in zip(draws, opening_development_scores["Flat p90", level, 100], strict=True))
    shape_split_dev_checks = assess_shape_split(shape_split_dev_comparison["typical"], shape_split_dev_magnitude["typical"],
                                               shape_split_gates, shape_split_clean_preserved, shape_split_dev_shared)
    shape_split_advances = all(shape_split_dev_checks.values())
    return (
        shape_split_advances,
        shape_split_clean_checks,
        shape_split_dev_checks,
        shape_split_dev_comparison,
        shape_split_dev_magnitude,
        shape_split_development,
    )


@app.cell(hide_code=True)
def _(
    mo,
    shape_split_advances,
    shape_split_clean_checks,
    shape_split_dev_checks,
    shape_split_dev_comparison,
    shape_split_dev_magnitude,
):
    _comparison = [{"noise": level, "check": row["contrast"],
                    "benchmark → shape-only / 64": f"{row['benchmark passes']} → {row['shape-only passes']}",
                    "seeds gained / lost": f"+{row['gained']} / −{row['lost']}",
                    "median margin: benchmark → shape-only": f"{row['benchmark median margin']:+.4f} → {row['shape-only median margin']:+.4f}"}
                   for level, summaries in shape_split_dev_comparison.items() for row in summaries]
    _ordinary = [{"noise": level, "check": row["contrast"],
                  "ordinary benchmark → shape-only / 64": f"{row['benchmark ordinary']} → {row['shape-only ordinary']}" if row["benchmark ordinary"] is not None else "—",
                  "ordinary median margin": f"{row['benchmark ordinary median margin']:+.4f} → {row['shape-only ordinary median margin']:+.4f}" if row["benchmark ordinary median margin"] is not None else "—",
                  "all-seven size passes / 64": f"{row['benchmark all size onsets']} → {row['shape-only all size onsets']}" if row["benchmark all size onsets"] is not None else "—"}
                 for level, summaries in shape_split_dev_comparison.items() for row in summaries]
    _magnitude = [{"noise": level, "negative dips / 448": row["negative dips"], "both magnitude gaps / 64": row["both size gaps"],
                   "flat runs / 64": row["flat runs"], "weak-spike hits / 448": row["weak spike hits"],
                   **{f"MAE · {value}": round(error, 6) for value, error in row["MAE"].items()}}
                  for level, row in shape_split_dev_magnitude.items()]
    _failed = ", ".join(label for label, passes in shape_split_dev_checks.items() if not passes) or "none"
    shape_split_scores_view = mo.vstack([
        mo.md(f"""## Shape and magnitude: development comparison

    **{'Advances' if shape_split_advances else 'Does not advance'}**. Missed typical-jitter gates: **{_failed}**. Both views use the same median-of-five p90 run extractor and frozen clean scaling. Shape-only distance leaves out signed peak; the raw signed peak remains available separately. Each entry scores base 100, paired seeds 0–63; stress is not used to select the representation.

    **Read the first table:** A seed passes duration, recurrence or reversal when all required anchors have clear planted events and a strictly positive worst margin. Compare the intended feature gap, capped at the clean gap (one day, one run or two days to peak), with the farthest within-shape weekday distance. Size equivalence requires all three spike days detected and their maximum pairwise distance below half the clean one-day gap on at least six of seven weekdays. Its displayed margin is the sixth-best distance margin before checking detection."""),
        mo.ui.table(_comparison, selection=None, page_size=8, show_search=False),
        mo.md("**Typical development gates:** ≥42/64 duration passes and at least seven more than the benchmark’s ordinary weekday count; ≥48/64 each for recurrence, reversal, and size equivalence; all 448 dips negative; clean replays and extractors agree. Ordinary margins use the full distance to the same-onset contrast and are shown only as a reference."),
        mo.accordion({"Ordinary comparisons, magnitude and clean checks": mo.vstack([
            mo.ui.table(_ordinary, selection=None, page_size=8),
            mo.md("Signed peak is unchanged. Log-unit MAE is against log(level/100). Both magnitude gaps means the strongest lower-size peak is below the weakest higher-size peak by at least half the clean gap for each adjacent size pair."),
            mo.ui.table(_magnitude, selection=None, page_size=2),
            mo.ui.table(shape_split_clean_checks, selection=None, page_size=3),
        ])}),
    ])
    return (shape_split_scores_view,)


@app.cell(hide_code=True)
def _(shape_split_development, shape_split_gates, shape_split_pass):
    shape_split_reversal_groups = ("Pass", "Event only", "Margin only", "Both event and margin")
    shape_split_size_groups = ("Pass", "Detection only", "Distance only", "Both below six", "Different onsets")
    shape_split_failure_seed_rows = []
    for _draw in shape_split_development["typical"]:
        _reversal = _draw["contrasts"]["Shape-only"]["Reversal"]
        _events = all(row["event observed"] for row in _reversal)
        _margins = all(row["protected margin"] > 0 for row in _reversal)
        _size = _draw["size checks"]["Shape-only"]
        _needed = shape_split_gates["onsets for size equivalence"]
        _d = sum(row["all detected"] for row in _size)
        _g = sum(row["size margin"] > 0 for row in _size)
        _j = sum(row["all detected"] and row["size margin"] > 0 for row in _size)
        _r_group = shape_split_reversal_groups[2 * (not _margins) + (not _events)]
        if _j >= _needed:
            _s_group = "Pass"
        elif _d < _needed and _g < _needed:
            _s_group = "Both below six"
        elif _d < _needed:
            _s_group = "Detection only"
        elif _g < _needed:
            _s_group = "Distance only"
        else:
            _s_group = "Different onsets"
        assert (_r_group == "Pass") == shape_split_pass(_draw, "Shape-only", "Reversal", True, _needed)
        assert (_s_group == "Pass") == shape_split_pass(_draw, "Shape-only", "Size equivalence", True, _needed)
        shape_split_failure_seed_rows.append({
            "seed": _draw["seed"], "reversal outcome": _r_group,
            "reversal event pairs valid": sum(row["event observed"] for row in _reversal[::2]),
            "reversal directions with positive margin": sum(row["protected margin"] > 0 for row in _reversal),
            "size outcome": _s_group, "D: detected": _d, "G: geometry": _g, "J: both": _j,
        })

    shape_split_failure_counts = {
        check: {group: sum(row[key] == group for row in shape_split_failure_seed_rows) for group in groups}
        for check, key, groups in (("Reversal", "reversal outcome", shape_split_reversal_groups),
                                   ("Size equivalence", "size outcome", shape_split_size_groups))
    }
    shape_split_detection_patterns = {}
    for _draw in shape_split_development["typical"]:
        for _onset in _draw["size checks"]["Shape-only"]:
            _missing = ", ".join(str(size) for size, hit in zip((110, 125, 150), _onset["detected 110/125/150"], strict=True) if not hit) or "None"
            _geometry = "within cutoff" if _onset["size margin"] > 0 else "at or beyond cutoff"
            _key = (_missing, _geometry)
            shape_split_detection_patterns[_key] = shape_split_detection_patterns.get(_key, 0) + 1
    return (
        shape_split_detection_patterns,
        shape_split_failure_counts,
        shape_split_failure_seed_rows,
    )


@app.cell(hide_code=True)
def _(
    dates,
    dist,
    evaluation_metadata,
    first_price_logs,
    local_peak_eval_ids,
    median_opening_features,
    noise_histories,
    shape_split_development,
    shape_split_failure_seed_rows,
    shape_split_ids,
    shape_split_width,
    standardized_excursion_rows,
    weekdays,
):
    def shape_split_trace_rows(seed):
        paths = noise_histories["typical"][100][seed]
        features = tuple(median_opening_features(path, shape_split_width) for path in paths)
        projection = tuple(row[1:] for row in standardized_excursion_rows(features))
        return paths, features, projection


    shape_split_reversal_trace_seed = min(row["seed"] for row in shape_split_failure_seed_rows if row["reversal outcome"] != "Pass")
    _r_seed = shape_split_reversal_trace_seed
    _failed = next(row for row in shape_split_development["typical"][_r_seed]["contrasts"]["Shape-only"]["Reversal"]
                   if not row["event observed"] or row["protected margin"] <= 0)
    _paths, _features, _projection = shape_split_trace_rows(_r_seed)
    _anchor = _failed["anchor"]
    _shape = evaluation_metadata[_anchor]["shape"]
    _farthest = min((item for item in shape_split_ids[_shape] if item != _anchor),
                    key=lambda item: (-dist(_projection[_anchor], _projection[item]), item))
    shape_split_reversal_trace = {**_failed, "seed": _r_seed, "farthest peer": _farthest,
                                  "farthest peer weekday": evaluation_metadata[_farthest]["weekday"]}
    shape_split_reversal_peak_trace = []
    for _item in (_anchor, _failed["contrast"], _farthest):
        _logs = first_price_logs(_paths[_item])
        _peak = max(range(len(_logs)), key=lambda day: abs(_logs[day]))
        _expected = dates.index(evaluation_metadata[_item]["onset_date"]) + (2 if evaluation_metadata[_item]["shape"] == "Gradual rise, abrupt reversal" else 0)
        _timing = _features[_item][3]
        shape_split_reversal_peak_trace.append({"ID": _item, "shape": evaluation_metadata[_item]["shape"],
                                                "weekday": evaluation_metadata[_item]["weekday"], "expected peak day": _expected,
                                                "measured peak day": _peak, "peak-run start": _peak - _timing if _timing is not None else None,
                                                "elapsed timing": _timing})

    shape_split_size_trace = min((row for row in shape_split_failure_seed_rows if row["size outcome"] != "Pass"), key=lambda row: row["seed"])
    _s_seed = shape_split_size_trace["seed"]
    _paths, _features, _projection = shape_split_trace_rows(_s_seed)
    _size_failures = [row for row in shape_split_development["typical"][_s_seed]["size checks"]["Shape-only"]
                      if not row["all detected"] or row["size margin"] <= 0][:2]
    shape_split_size_onset_trace = []
    for _failed in _size_failures:
        _idx = weekdays.index(_failed["weekday"])
        _ids = sorted(local_peak_eval_ids[level][_idx] for level in (110, 125, 150))
        _pair = min(((-dist(_projection[a], _projection[b]), a, b) for i, a in enumerate(_ids) for b in _ids[i + 1:]))
        _distance, _a, _b = -_pair[0], _pair[1], _pair[2]
        _components = tuple((x - y) ** 2 for x, y in zip(_projection[_a], _projection[_b], strict=True))
        shape_split_size_onset_trace.append({
            "weekday": _failed["weekday"], "110 / 125 / 150 hit": " / ".join("yes" if hit else "no" for hit in _failed["detected 110/125/150"]),
            "farthest pair": f"ID {_a} / {_b}", "distance": _distance, "persistence squared": _components[0],
            "run count squared": _components[1], "timing squared": _components[2],
        })
    return (
        shape_split_reversal_peak_trace,
        shape_split_reversal_trace,
        shape_split_size_onset_trace,
        shape_split_size_trace,
    )


@app.cell(hide_code=True)
def _(
    feature_scales,
    mo,
    shape_split_detection_patterns,
    shape_split_failure_counts,
    shape_split_failure_seed_rows,
    shape_split_reversal_peak_trace,
    shape_split_reversal_trace,
    shape_split_size_onset_trace,
    shape_split_size_trace,
):
    _summary = [{"check": name, "seed outcome": label, "seeds / 64": count}
                for name, groups in shape_split_failure_counts.items() for label, count in groups.items()]
    _patterns = [{"missed planted spike size(s)": missing, "shape distance": geometry, "onsets (448 total)": count}
                 for (missing, geometry), count in sorted(shape_split_detection_patterns.items())]
    _r = shape_split_reversal_trace
    _s = shape_split_size_trace
    shape_split_failure_view = mo.vstack([
        mo.md(f"""## Shape and magnitude: why the two gates failed

    **Development diagnosis only:** typical jitter, base 100, same 64 seeds, no refit or fresh draws. For reversal, separate planted-peak evidence (correct dates and observed run timing for all seven pairs) from distance evidence (all 14 directional margins positive). For size equivalence, **D** counts onsets with all three planted spikes detected and **G** counts onsets inside the shape-distance cutoff. At least six onsets must satisfy **both on the same day (J)**. The seed-level groups below are mutually exclusive."""),
        mo.ui.table(_summary, selection=None, page_size=9, show_search=False),
        mo.accordion({"Lowest-numbered failures, onset patterns and seed records": mo.vstack([
            mo.md(f"""**Reversal seed {_r['seed']}, {_r['weekday']}:** anchor ID {_r['anchor']}; farthest peer ID {_r['farthest peer']} ({_r['farthest peer weekday']}). Intended credit **{_r['intended credit']:+.4f}**, within-shape distance **{_r['within distance']:.4f}**, margin **{_r['protected margin']:+.4f}**. Day numbers are zero-based. N/A run timing is not observed evidence."""),
            mo.ui.table(shape_split_reversal_peak_trace, selection=None, page_size=3),
            mo.md(f"**Size-equivalence seed {_s['seed']}:** D/G/J = {_s['D: detected']}/{_s['G: geometry']}/{_s['J: both']}. The first two failing weekdays are shown (one is allowed). Squared components sum to the farthest pair’s squared shape distance; cutoff **{0.5 / feature_scales[1]:.4f}**."),
            mo.ui.table(shape_split_size_onset_trace, selection=None, page_size=2,
                        format_mapping={key: "{:.6f}".format for key in ("distance", "persistence squared", "run count squared", "timing squared")}),
            mo.ui.table(_patterns, selection=None, page_size=10),
            mo.ui.table(shape_split_failure_seed_rows, selection=None, page_size=8),
        ])}),
    ])
    return (shape_split_failure_view,)


@app.cell(hide_code=True)
def _(
    cohort_distances,
    evaluation_metadata,
    history_index,
    mo,
    pca_coordinates,
    selected_cluster_labels,
    umap_coordinates,
):
    _sat = history_index[("One-day spike (150)", "Saturday")]
    _fri = history_index[("One-day spike (150)", "Friday")]
    _plateau = history_index[("Two-day plateau", "Saturday")]
    _opening_rows = [{"history ID": _id, "shape": evaluation_metadata[_id]["shape"], "weekday": evaluation_metadata[_id]["weekday"], "cluster": selected_cluster_labels[_id], "distance from Saturday spike": cohort_distances[_sat][_id], "PCA 1": float(pca_coordinates[_id][0]), "PCA 2": float(pca_coordinates[_id][1]), "UMAP 1": float(umap_coordinates[_id][0]), "UMAP 2": float(umap_coordinates[_id][1])} for _id in [_fri, _sat, _plateau]]
    projection_coordinates_view = mo.vstack([mo.md("### Opening histories: IDs, assignments and full-space distances. The Saturday spike is the distance anchor; these distances are not measured on either projection."), mo.ui.table(_opening_rows, selection=None, page_size=3)])
    return (projection_coordinates_view,)


@app.cell(hide_code=True)
def _(mo, replay_summary):
    proportional_replay_view = mo.vstack([mo.md("## Scale and noise robustness\n\n### Clean proportional replay\nEach base replays all 71 matched histories without rounding. Features use the same extractor; the base-100 timing fill, means and population scales are reused without refitting. Changes and distances retain full precision. Timing N/A includes the flat control. Equal proportional paths are expected to agree up to floating-point rounding."), mo.ui.table(replay_summary, selection=None, page_size=3)])
    return (proportional_replay_view,)


@app.cell(hide_code=True)
def _(
    calibration_lag1_correlation,
    calibration_median_abs_return,
    calibration_p90_abs_return,
    calibration_zero_fraction,
    jitter_innovation_sd,
    jitter_level_sd,
    jitter_phi,
    jitter_stress_multiplier,
    mo,
    noise_summary,
):
    generator_calibration_view = mo.vstack([mo.md(f"""### Untuned log-price jitter

    Fixed calibration inputs are medians of per-item return statistics from Forge region 10000002 (2022-06-01–2026-09-01): 99 items, 153,294 finite-positive adjacent-day VWAP log returns and 153,018 consecutive return pairs, zeros included. Median absolute return {calibration_median_abs_return}, p90 {calibration_p90_abs_return}, lag-1 correlation {calibration_lag1_correlation}, and zero fraction {calibration_zero_fraction} describe observed variation, not labeled noise.

    The typical model is a stationary Gaussian AR(1) **log-level** process: phi = 1 + 2ρ = {jitter_phi:.6f}; stationary level SD = {jitter_level_sd:.8f}; innovation SD = {jitter_innovation_sd:.8f}. Its return SD is set using the normal absolute-return median. Stress multiplies the **same** offsets by {jitter_stress_multiplier:.6f}, matching the observed p90 against the model's normal absolute-return p90; it is not a fat-tail fit. Each path is multiplied by exp(Xₜ − X₀), preserving its first price. These are distribution targets, not promises for one 21-day draw.

    Seeds 0–63 use Python `random.Random(seed)` and stationary Gaussian initialization. Each seed's background is reused across shapes, weekdays, bases and both levels: these are paired variations, not independent observations. The clean extractor and base-100 preprocessing stay frozen; no tolerance or refit is applied. Median/max displacement is measured from the matching clean row. The strict weekday fraction counts seeds for which all seven margins are positive. Flat run lengths are measured by the same extractor."""), mo.ui.table(noise_summary, selection=None, page_size=6)])
    return (generator_calibration_view,)


@app.cell(hide_code=True)
def _(mo, noise_feature_summary):
    feature_drift_view = mo.vstack([mo.md("### Feature drift from matched clean paths. Changed-row counts use exact comparisons; timing drift excludes N/A pairs, whose status changes are counted separately. Values are absolute and unrounded."), mo.ui.table(noise_feature_summary, selection=None, page_size=12)])
    return (feature_drift_view,)


@app.cell(hide_code=True)
def _(mo, noise_example_neighbors):
    untuned_neighbors_view = mo.vstack([mo.md("### Noisy full-space neighbors: typical, base 100, seed 0. The Saturday 150 spike is the query; self is excluded. The first five positions and every tie at the cutoff are shown with shared ranks. Distances use the frozen standardized feature space, not projection coordinates or clean neighbors."), mo.ui.table(noise_example_neighbors, selection=None, page_size=10)])
    return (untuned_neighbors_view,)


@app.cell(hide_code=True)
def _(
    dist,
    evaluation_metadata,
    feature_means,
    feature_scales,
    history_index,
    log,
    reference,
    timing_fill,
    weekdays,
):
    from math import expm1, isclose
    from statistics import quantiles


    def first_price_logs(history):
        return tuple(log(price / history[0]) for price in history)


    def band_features(history, width, reference=None):
        logs = first_price_logs(history)
        reference = history[0] if reference is None else reference
        peak = max(range(len(logs)), key=lambda day: abs(logs[day]))
        length = longest = runs = 0
        timing = None
        for day in range(len(history)):
            outside = history[day] != reference if width == 0 else abs(log(history[day] / reference)) > width
            if outside:
                runs += length == 0
                length += 1
                longest = max(longest, length)
                if day == peak:
                    timing = length - 1
            else:
                length = 0
        return logs[peak], longest, runs, timing


    def standardized_excursion_rows(rows):
        return tuple(
            tuple((value - mean) / scale for value, mean, scale in zip(
                (*row[:3], timing_fill if row[3] is None else row[3]),
                feature_means, feature_scales, strict=True,
            ))
            for row in rows
        )


    def excursion_weekday_margin(rows):
        spikes = [history_index[("One-day spike (150)", day)] for day in weekdays]
        plateaus = [history_index[("Two-day plateau", day)] for day in weekdays]
        return min(
            dist(rows[anchor], rows[plateau])
            - max(dist(rows[anchor], rows[other]) for other in spikes if other != anchor)
            for anchor, plateau in zip(spikes, plateaus, strict=True)
        )


    def excursion_neighbors(rows):
        query = history_index[("One-day spike (150)", "Saturday")]
        nearest = sorted((dist(rows[query], row), item) for item, row in enumerate(rows) if item != query)
        cutoff = nearest[4][0]
        result = []
        for position, (distance, item) in enumerate(nearest, 1):
            if distance > cutoff and not isclose(distance, cutoff, rel_tol=0, abs_tol=1e-12):
                break
            if position == 1 or not isclose(distance, reference, rel_tol=0, abs_tol=1e-12):
                rank, reference = position, distance
            result.append({"rank": rank, "ID": item, "shape": evaluation_metadata[item]["shape"],
                           "onset": evaluation_metadata[item]["weekday"] or "—", "distance": round(distance, 6)})
        return result

    return (
        band_features,
        excursion_neighbors,
        excursion_weekday_margin,
        expm1,
        first_price_logs,
        isclose,
        quantiles,
        standardized_excursion_rows,
    )


@app.cell(hide_code=True)
def _(
    dates,
    evaluation_metadata,
    excursion_weekday_margin,
    history_index,
    standardized_excursion_rows,
    weekdays,
):
    excursion_flat_id = history_index[("Flat reference", None)]
    weak_spike_onsets = tuple(
        (item, dates.index(evaluation_metadata[item]["onset_date"]))
        for item in (history_index[("One-day spike (110)", day)] for day in weekdays)
    )


    def score_excursion_draws(draws, describe, upward_on):
        """One row per seed. Planted labels enter only this evaluator."""
        result = []
        for seed, histories in draws.items():
            features = tuple(describe(history) for history in histories)
            rows = standardized_excursion_rows(features)
            result.append({
                "seed": seed,
                "flat any run": features[excursion_flat_id][1] > 0,
                "spike hits": sum(upward_on(histories[item], day) for item, day in weak_spike_onsets),
                "weekday margin": excursion_weekday_margin(rows),
            })
        return result


    def summarize_excursion_scores(scores):
        return {
            "flat any run": sum(row["flat any run"] for row in scores) / len(scores),
            "10% spike-day recall": sum(row["spike hits"] for row in scores) / (len(scores) * len(weak_spike_onsets)),
            "all-seven weekday pass": sum(row["weekday margin"] > 0 for row in scores) / len(scores),
            "worst weekday margin": min(row["weekday margin"] for row in scores),
        }

    return (
        excursion_flat_id,
        score_excursion_draws,
        summarize_excursion_scores,
        weak_spike_onsets,
    )


@app.cell(hide_code=True)
def _(
    band_features,
    excursion_flat_id,
    excursion_neighbors,
    expm1,
    first_price_logs,
    log,
    noise_histories,
    price_histories,
    quantiles,
    score_excursion_draws,
    standardized_excursion_rows,
):
    flat_peak_dev = tuple(max(map(abs, first_price_logs(draw[excursion_flat_id])))
                          for draw in noise_histories["typical"][100].values())
    _percentiles = quantiles(flat_peak_dev, n=100, method="inclusive")
    band_development_widths = {"Zero": 0.0, **{f"Flat p{p}": _percentiles[p - 1] for p in (80, 90, 95)}}
    band_development_scores = {}
    band_clean_checks = []
    band_example_neighbors = []
    for _label, _width in band_development_widths.items():
        _clean = score_excursion_draws({0: price_histories},
                                       lambda history: band_features(history, _width),
                                       lambda history, day: first_price_logs(history)[day] > _width)[0]
        band_clean_checks.append({"width source": _label, "log width": round(_width, 6),
                                  "upper edge above first price": f"{expm1(_width):.2%}",
                                  "erases clean 10% spike": _width >= log(1.10),
                                  "clean spike days retained": _clean["spike hits"],
                                  "clean flat has run": _clean["flat any run"],
                                  "clean worst margin": round(_clean["weekday margin"], 6)})
        for _level, _bases in noise_histories.items():
            for _base, _draws in _bases.items():
                band_development_scores[_label, _level, _base] = score_excursion_draws(
                    _draws, lambda history: band_features(history, _width),
                    lambda history, day: first_price_logs(history)[day] > _width,
                )
        _example = standardized_excursion_rows(tuple(band_features(path, _width) for path in noise_histories["typical"][100][0]))
        band_example_neighbors.extend({"width source": _label, **row} for row in excursion_neighbors(_example))
    return (
        band_clean_checks,
        band_development_scores,
        band_development_widths,
        band_example_neighbors,
    )


@app.cell(hide_code=True)
def _(
    band_clean_checks,
    band_development_scores,
    band_example_neighbors,
    mo,
    summarize_excursion_scores,
):
    _rate_keys = ("flat any run", "10% spike-day recall", "all-seven weekday pass")
    _summary = [{"width source": label, "noise": level, "base": base,
                 **{k: (f"{value:.1%}" if k in _rate_keys else f"{value:+.3f}")
                    for k, value in summarize_excursion_scores(scores).items()}}
                for (label, level, base), scores in band_development_scores.items()]
    first_price_development_view = mo.vstack([
        mo.md("""### Development: can a fixed band distinguish jitter from events?

    Days inside the symmetric log band end a run; only an outside day starts one. The signed raw peak, first-price reference and base-100 preprocessing stay fixed. The candidate widths are the typical/base-100 flat controls’ per-path maximums (seeds 0–63, linearly interpolated percentiles), not day-level percentiles. Zero is the exact-baseline comparison. The band is applied unchanged at every base and both noise levels.

    **Read the trade-off:** flat paths should have no run; a 10% spike is a hit only if its planted day is outside the band on the positive side. Each noise/base cell has 64 flat paths and 448 paired spike days. Weekday success requires all seven 150-spike shifts to stay closer than the corresponding same-onset plateau; the signed worst margin shows the largest failure. The clean check comes first so a width that erases the noiseless 10% spike cannot pass unnoticed."""),
        mo.ui.table(band_clean_checks, selection=None, page_size=4),
        mo.ui.table([row for row in _summary if row["base"] == 100], selection=None, page_size=8),
        mo.accordion({"All base levels": mo.ui.table(_summary, selection=None, page_size=12),
                      "Neighbor example · typical / base 100 / seed 0": mo.vstack([
                          mo.md("Query: Saturday 150 spike. Five positions plus all cutoff ties; distances are in the frozen four-feature space."),
                          mo.ui.table(band_example_neighbors, selection=None, page_size=8),
                      ])}),
    ])
    return (first_price_development_view,)


@app.cell(hide_code=True)
def _(
    band_features,
    excursion_flat_id,
    log,
    median,
    noise_histories,
    quantiles,
    replay_features,
    replay_histories,
    score_excursion_draws,
):
    def median_opening(history):
        return median(history[:5])


    def median_opening_features(history, width):
        return band_features(history, width, median_opening(history))


    def median_opening_upward(history, day, width):
        return log(history[day] / median_opening(history)) > width


    _maxima = [max(abs(log(value / median_opening(path))) for value in path)
               for draw in noise_histories["typical"][100].values()
               for path in [draw[excursion_flat_id]]]
    _percentiles = quantiles(_maxima, n=100, method="inclusive")
    opening_widths = {"Zero": 0.0, **{f"Flat p{p}": _percentiles[p - 1] for p in (80, 90, 95)}}
    opening_development_scores = {}
    opening_clean_checks = []
    for _label, _width in opening_widths.items():
        for _base, _histories in replay_histories.items():
            _features = tuple(median_opening_features(path, _width) for path in _histories)
            _expected = tuple((*row[:3], row[3]["days_to_peak"]) for row in replay_features[_base])
            _scores = score_excursion_draws({0: _histories},
                                           lambda history: median_opening_features(history, _width),
                                           lambda history, day: median_opening_upward(history, day, _width))[0]
            opening_clean_checks.append({"width source": _label, "base": _base,
                                         "rows unchanged": _features == _expected,
                                         "flat timing N/A": _features[excursion_flat_id][3] is None,
                                         "clean spike hits": _scores["spike hits"],
                                         "clean weekday margin": _scores["weekday margin"]})
        for _level, _bases in noise_histories.items():
            for _base, _draws in _bases.items():
                opening_development_scores[_label, _level, _base] = score_excursion_draws(
                    _draws, lambda history: median_opening_features(history, _width),
                    lambda history, day: median_opening_upward(history, day, _width),
                )
    return (
        median_opening,
        median_opening_features,
        median_opening_upward,
        opening_clean_checks,
        opening_development_scores,
        opening_widths,
    )


@app.cell(hide_code=True)
def _(
    band_development_scores,
    isclose,
    opening_clean_checks,
    opening_development_scores,
    smallest_margin,
):
    def paired_excursion_delta(candidate, comparator):
        result = []
        for left, right in zip(candidate, comparator, strict=True):
            assert left["seed"] == right["seed"]
            result.append({
                "seed": left["seed"],
                "flat-run change": int(left["flat any run"]) - int(right["flat any run"]),
                "spike-hit change": left["spike hits"] - right["spike hits"],
                "margin change": left["weekday margin"] - right["weekday margin"],
                "weekday-pass change": int(left["weekday margin"] > 0) - int(right["weekday margin"] > 0),
            })
        return result


    opening_paired_deltas = {key: paired_excursion_delta(rows, band_development_scores[key])
                             for key, rows in opening_development_scores.items()}
    _target = ("Flat p90", "typical", 100)
    _p90_deltas = opening_paired_deltas[_target]
    _p90_scores = opening_development_scores[_target]
    opening_p90_gates = {
        "clean preserved": all(row["rows unchanged"] and row["flat timing N/A"]
                               and row["clean spike hits"] == 7
                               and isclose(row["clean weekday margin"], smallest_margin, rel_tol=0, abs_tol=1e-12)
                               for row in opening_clean_checks if row["width source"] == "Flat p90"),
        "flat paths with a run": sum(row["flat any run"] for row in _p90_scores),
        "additional spike hits": sum(row["spike-hit change"] for row in _p90_deltas),
        "passing weekday draws": sum(row["weekday margin"] > 0 for row in _p90_scores),
    }
    opening_p90_advances = (opening_p90_gates["clean preserved"]
                            and opening_p90_gates["flat paths with a run"] <= 7
                            and opening_p90_gates["additional spike hits"] >= 23
                            and opening_p90_gates["passing weekday draws"] >= 35)
    return (
        opening_p90_advances,
        opening_p90_gates,
        opening_paired_deltas,
        paired_excursion_delta,
    )


@app.cell(hide_code=True)
def _(
    band_development_scores,
    band_development_widths,
    expm1,
    median,
    mo,
    opening_clean_checks,
    opening_development_scores,
    opening_p90_advances,
    opening_p90_gates,
    opening_paired_deltas,
    opening_widths,
    summarize_excursion_scores,
):
    _comparison = []
    for (_label, _level, _base), _rows in opening_development_scores.items():
        _first = band_development_scores[_label, _level, _base]
        _diff = opening_paired_deltas[_label, _level, _base]
        _left, _right = summarize_excursion_scores(_first), summarize_excursion_scores(_rows)
        _comparison.append({
            "noise": _level, "base": _base, "width source": _label,
            "flat runs / 64 (first → median-5)": f"{sum(r['flat any run'] for r in _first)} → {sum(r['flat any run'] for r in _rows)}",
            "spike-day recall (first → median-5)": f"{_left['10% spike-day recall']:.1%} → {_right['10% spike-day recall']:.1%}",
            "added spike hits / 448": sum(r["spike-hit change"] for r in _diff),
            "weekday passes / 64 (first → median-5)": f"{sum(r['weekday margin'] > 0 for r in _first)} → {sum(r['weekday margin'] > 0 for r in _rows)}",
            "worst margin (first → median-5)": f"{_left['worst weekday margin']:+.3f} → {_right['worst weekday margin']:+.3f}",
            "median paired margin change": f"{median(r['margin change'] for r in _diff):+.3f}",
        })
    _widths = [{"width source": label, "first price log width": round(band_development_widths[label], 6),
                "median-5 log width": round(width, 6), "median-5 upper edge": f"{expm1(width):.2%}"}
               for label, width in opening_widths.items()]
    _gates = opening_p90_gates
    median_opening_development_view = mo.vstack([
        mo.md(f"""### Development: does a quieter opening reference recover weak spikes?

    The first five prices define a fixed median reference for runs; all 21 days are scored, including those five. The raw signed peak still uses the first price; its timing is N/A if that day is inside the run band. Each reference gets its own width from typical/base-100 flat maxima; everything else stays frozen. This tests retrospective descriptions with a quiet opening, not events already in progress.

    **p90 {'advances to confirmation' if opening_p90_advances else 'does not advance'}.** On typical noise, median-5 p90 {'preserves' if _gates['clean preserved'] else 'changes'} the clean rows; it gives **{_gates['flat paths with a run']}/64** false flat runs (require ≤7), **{_gates['additional spike hits']:+d}/448** weak-spike hits versus first-price p90 (require ≥23 additional), and **{_gates['passing weekday draws']}/64** all-seven weekday passes (require ≥35). Those gates were set before running this comparison. Stress is a separate readout, not a tuning target."""),
        mo.ui.table([row for row in _comparison if row["base"] == 100], selection=None, page_size=8),
        mo.accordion({"Exact widths and all-base clean checks": mo.vstack([
            mo.ui.table(_widths, selection=None, page_size=4),
            mo.ui.table(opening_clean_checks, selection=None, page_size=12),
        ]), "All-base comparisons and paired p90 seed rows": mo.vstack([
            mo.ui.table(_comparison, selection=None, page_size=12),
            mo.ui.table([{"noise": level, **row} for level in ("typical", "stress")
                         for row in opening_paired_deltas["Flat p90", level, 100]], selection=None, page_size=8),
        ])}),
        mo.md("Read left to right: first-price band → median-5 band. Each seed contributes one flat control and seven paired spike days; the other bases replay the same draws. The paired margin change compares each seed's smallest margin before taking the median."),
    ])
    return (median_opening_development_view,)


@app.cell(hide_code=True)
def _(
    band_development_widths,
    band_features,
    first_price_logs,
    jitter_seeds,
    median_opening_features,
    median_opening_upward,
    opening_p90_advances,
    opening_widths,
):
    holdout_seeds = tuple(range(64, 576))
    holdout_widths = {"First-price p90": band_development_widths["Flat p90"],
                      "Median-5 p90": opening_widths["Flat p90"]}
    holdout_gates = {"max flat runs": 56, "min added hits": 184, "min weekday passes": 280}
    holdout_bootstrap_n = 10_000
    holdout_bootstrap_seed = 20261120


    def describe_locked_band(history, method, width):
        return (median_opening_features if method == "Median-5 p90" else band_features)(history, width)


    def locked_upward_hit(history, day, method, width):
        return (median_opening_upward(history, day, width) if method == "Median-5 p90"
                else first_price_logs(history)[day] > width)


    assert opening_p90_advances and not set(jitter_seeds).intersection(holdout_seeds)
    return (
        describe_locked_band,
        holdout_bootstrap_n,
        holdout_bootstrap_seed,
        holdout_gates,
        holdout_seeds,
        holdout_widths,
        locked_upward_hit,
    )


@app.cell(hide_code=True)
def _(
    describe_locked_band,
    excursion_flat_id,
    excursion_neighbors,
    excursion_weekday_margin,
    holdout_seeds,
    holdout_widths,
    locked_upward_hit,
    make_jitter_multipliers,
    replay_features,
    replay_histories,
    score_excursion_draws,
    standardized_excursion_rows,
    weak_spike_onsets,
):
    holdout_scores = {}
    holdout_clean_checks = []
    holdout_neighbors = []
    _multipliers = make_jitter_multipliers(holdout_seeds)
    for _base, _histories in replay_histories.items():
        _reference = tuple((*row[:3], row[3]["days_to_peak"]) for row in replay_features[_base])
        for _method, _width in holdout_widths.items():
            _features = tuple(describe_locked_band(path, _method, _width) for path in _histories)
            holdout_clean_checks.append({
                "base": _base, "rule": _method, "rows unchanged": _features == _reference,
                "flat timing N/A": _features[excursion_flat_id][3] is None,
                "clean hits": sum(locked_upward_hit(_histories[item], day, _method, _width)
                                  for item, day in weak_spike_onsets),
                "weekday margin": excursion_weekday_margin(standardized_excursion_rows(_features)),
            })
        for _level, _seed_paths in _multipliers.items():
            _draws = {seed: tuple(tuple(price * factor for price, factor in zip(path, factors, strict=True))
                                  for path in _histories)
                      for seed, factors in _seed_paths.items()}
            for _method, _width in holdout_widths.items():
                holdout_scores[_level, _base, _method] = score_excursion_draws(
                    _draws, lambda path: describe_locked_band(path, _method, _width),
                    lambda path, day: locked_upward_hit(path, day, _method, _width),
                )
                if _level == "typical" and _base == 100:
                    _first_draw = _draws[holdout_seeds[0]]
                    _example = standardized_excursion_rows(tuple(describe_locked_band(path, _method, _width)
                                                                   for path in _first_draw))
                    holdout_neighbors.extend({"rule": _method, **row} for row in excursion_neighbors(_example))

    holdout_replay = []
    for (_level, _base, _method), _scores in holdout_scores.items():
        if _base == 100:
            continue
        _base100 = holdout_scores[_level, 100, _method]
        holdout_replay.append({
            "noise": _level, "base": _base, "rule": _method,
            "flat disagreements": sum(a["flat any run"] != b["flat any run"] for a, b in zip(_scores, _base100, strict=True)),
            "spike-hit count disagreements": sum(a["spike hits"] != b["spike hits"] for a, b in zip(_scores, _base100, strict=True)),
            "weekday pass disagreements": sum((a["weekday margin"] > 0) != (b["weekday margin"] > 0)
                                              for a, b in zip(_scores, _base100, strict=True)),
            "max absolute margin change": max(abs(a["weekday margin"] - b["weekday margin"])
                                              for a, b in zip(_scores, _base100, strict=True)),
        })
    return (
        holdout_clean_checks,
        holdout_neighbors,
        holdout_replay,
        holdout_scores,
    )


@app.cell(hide_code=True)
def _(
    Random,
    holdout_bootstrap_n,
    holdout_bootstrap_seed,
    holdout_clean_checks,
    holdout_gates,
    holdout_scores,
    holdout_seeds,
    isclose,
    median,
    paired_excursion_delta,
    quantiles,
    smallest_margin,
    weak_spike_onsets,
):
    holdout_levels = ("typical", "stress")
    holdout_deltas = {level: paired_excursion_delta(holdout_scores[level, 100, "Median-5 p90"],
                                                    holdout_scores[level, 100, "First-price p90"])
                      for level in holdout_levels}
    holdout_clean_preserved = all(row["rows unchanged"] and row["flat timing N/A"] and row["clean hits"] == 7
                                  and isclose(row["weekday margin"], smallest_margin, rel_tol=0, abs_tol=1e-12)
                                  for row in holdout_clean_checks)
    holdout_outcome = {}
    holdout_rate_differences = []
    holdout_margin_differences = {}
    _n_draws = len(holdout_seeds)
    _n_spikes = _n_draws * len(weak_spike_onsets)
    for _level, _rows in holdout_deltas.items():
        _candidate = holdout_scores[_level, 100, "Median-5 p90"]
        _flat = sum(row["flat any run"] for row in _candidate)
        _gained = sum(row["spike-hit change"] for row in _rows)
        _passes = sum(row["weekday margin"] > 0 for row in _candidate)
        holdout_outcome[_level] = {
            "flat runs": _flat, "added hits": _gained, "weekday passes": _passes,
            "confirmed": holdout_clean_preserved and _flat <= holdout_gates["max flat runs"]
            and _gained >= holdout_gates["min added hits"] and _passes >= holdout_gates["min weekday passes"],
        }
        holdout_margin_differences[_level] = median(row["margin change"] for row in _rows)

    # Reuse the bootstrap draw indices for all paired metrics. Each index is an entire seed.
    _keys = ("flat-run change", "spike-hit change", "weekday-pass change")
    _denominators = (_n_draws, _n_spikes, _n_draws)
    _series = [(_level, key, denominator, tuple(row[key] for row in holdout_deltas[_level]), [])
               for _level in holdout_levels for key, denominator in zip(_keys, _denominators, strict=True)]
    _rng = Random(holdout_bootstrap_seed)
    for _resample in range(holdout_bootstrap_n):
        _indices = _rng.choices(range(_n_draws), k=_n_draws)
        for _noise, _metric, _denominator, _values, _bootstrap in _series:
            _bootstrap.append(sum(_values[index] for index in _indices) / _denominator)
    for _level, _key, _denominator, _values, _bootstrap in _series:
        _percentiles = quantiles(_bootstrap, n=200, method="inclusive")
        holdout_rate_differences.append({
            "noise": _level, "metric": _key, "change": sum(_values) / _denominator,
            "95% low": _percentiles[4], "95% high": _percentiles[194],
        })
    return (
        holdout_levels,
        holdout_margin_differences,
        holdout_outcome,
        holdout_rate_differences,
    )


if __name__ == "__main__":
    app.run()
