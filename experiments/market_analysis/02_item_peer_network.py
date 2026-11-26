import marimo

__generated_with = "0.26.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    from datetime import date, timedelta
    from pathlib import Path

    import anywidget
    import marimo as mo
    import numpy as np
    import polars as pl
    import traitlets
    from transform.notebook_access import open_analysis_connection

    return (
        Path,
        anywidget,
        date,
        mo,
        np,
        open_analysis_connection,
        pl,
        timedelta,
        traitlets,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Weekly item peer network

    Links summarize how often two items move to the same side of the median of other observed items. This is descriptive, not causal; short windows are exploratory. Weekly prices are traded-volume-weighted VWAPs, and changes require adjacent complete calendar weeks.

    Positions start in study-category regions, then evolve with the links; proximity and grouping are layout aids, not measured relationships.

    At least 60% of the trailing weeks must have usable paired changes; ties are usable but do not agree. The first snapshot is inventory, not additions. Threshold reversals are displayed link changes, not market events.
    """)


@app.cell(hide_code=True)
def _(date, open_analysis_connection, pl):
    STUDY_START = date(2022, 6, 1)
    STUDY_END = date(2026, 9, 1)
    with open_analysis_connection() as connection:
        history_df = connection.execute(
            """
            select type_id, type_name, study_category, market_date, average as vwap, volume
            from main.int_study_panel_history
            where market_date between ? and ? order by type_id, market_date
        """,
            [STUDY_START, STUDY_END],
        ).pl()
    if history_df.is_empty():
        raise ValueError("The configured study period has no history.")
    if history_df.select(pl.struct("type_id", "market_date").is_duplicated().any()).item():
        raise ValueError("Expected one row per item and date.")
    item_df = history_df.select("type_id", "type_name", "study_category").unique().sort("type_id")
    if item_df.select(pl.col("type_id").is_duplicated().any()).item():
        raise ValueError("Inconsistent item metadata.")
    return STUDY_END, STUDY_START, history_df, item_df


@app.cell(hide_code=True)
def _(STUDY_END, STUDY_START, history_df, item_df, np, pl, timedelta):
    first_week = STUDY_START + timedelta(days=(6 - STUDY_START.weekday()) % 7)
    last_saturday = STUDY_END - timedelta(days=(STUDY_END.weekday() - 5) % 7)
    last_week = last_saturday - timedelta(days=6)
    valid_df = history_df.filter(
        pl.col("vwap").is_finite() & (pl.col("vwap") > 0) & (pl.col("volume") > 0)
    ).with_columns((pl.col("market_date") - pl.duration(days=pl.col("market_date").dt.weekday() % 7)).alias("week"))
    valid_df = valid_df.filter(pl.col("week").is_between(first_week, last_week))
    weekly_df = valid_df.group_by("type_id", "week").agg(
        ((pl.col("vwap") * pl.col("volume")).sum() / pl.col("volume").sum()).alias("price")
    )
    week_dates = [first_week + timedelta(weeks=i) for i in range((last_week - first_week).days // 7 + 1)]
    item_ids = item_df["type_id"].to_list()
    price_matrix = np.full((len(week_dates), len(item_ids)), np.nan)
    week_index = {week: i for i, week in enumerate(week_dates)}
    item_index = {item: i for i, item in enumerate(item_ids)}
    for _item, _week, _price in weekly_df.iter_rows():
        price_matrix[week_index[_week], item_index[_item]] = _price
    changes = np.full_like(price_matrix, np.nan)
    changes[1:] = price_matrix[1:] / price_matrix[:-1] - 1
    return changes, item_ids, week_dates


@app.cell(hide_code=True)
def _(np):
    def paired_agreement(values, left, right):
        if not (np.isfinite(values[left]) and np.isfinite(values[right])):
            return False, False
        other = values[np.isfinite(values) & (np.arange(len(values)) != left) & (np.arange(len(values)) != right)]
        if not len(other):
            return False, False
        median = np.median(other)
        agrees = (values[left] > median and values[right] > median) or (
            values[left] < median and values[right] < median
        )
        return True, agrees

    return (paired_agreement,)


@app.cell(hide_code=True)
def _(changes, item_ids, np, paired_agreement, week_dates):
    pair_left, pair_right = np.triu_indices(len(item_ids), 1)
    usable = np.zeros((len(week_dates), len(pair_left)), dtype=bool)
    agreement = np.zeros_like(usable)
    for _week in range(1, len(week_dates)):
        values = changes[_week]
        for pair, (left, right) in enumerate(zip(pair_left, pair_right, strict=False)):
            usable[_week, pair], agreement[_week, pair] = paired_agreement(values, left, right)
    usable_prefix = np.vstack(
        [np.zeros((1, len(pair_left)), dtype=np.int32), np.cumsum(usable, axis=0, dtype=np.int32)]
    )
    agreement_prefix = np.vstack(
        [np.zeros((1, len(pair_left)), dtype=np.int32), np.cumsum(agreement, axis=0, dtype=np.int32)]
    )
    return agreement_prefix, pair_left, pair_right, usable, usable_prefix


@app.cell(hide_code=True)
def _(agreement_prefix, np, usable_prefix, week_dates):
    def window_scores(length):
        ends = np.arange(length + 1, len(week_dates) + 1)
        counts = usable_prefix[ends] - usable_prefix[ends - length]
        wins = agreement_prefix[ends] - agreement_prefix[ends - length]
        scores = np.divide(wins, counts, out=np.zeros_like(wins, dtype=float), where=counts > 0)
        return ends - 1, counts, wins, scores

    def replay(length, entry, exit, prepared, fresh_usable):
        weeks, counts, wins, scores = prepared
        eligible = counts >= int(np.ceil(0.6 * length))
        active = np.zeros_like(eligible)
        ages = np.zeros_like(counts, dtype=np.int16)
        for row, week in enumerate(weeks):
            previous = active[row - 1] if row else np.zeros(counts.shape[1], dtype=bool)
            active[row] = eligible[row] & np.where(
                previous, scores[row] >= exit, (scores[row] >= entry) & fresh_usable[week]
            )
            old_age = ages[row - 1] if row else np.zeros(counts.shape[1], dtype=np.int16)
            ages[row] = np.where(active[row], np.where(previous, old_age + fresh_usable[week], 1), 0)
        additions = np.zeros(len(weeks), dtype=int)
        removals = np.zeros(len(weeks), dtype=int)
        additions[1:] = (active[1:] & ~active[:-1]).sum(axis=1)
        removals[1:] = (active[:-1] & ~active[1:]).sum(axis=1)
        return weeks, counts, wins, scores, active, ages, additions, removals

    return replay, window_scores


@app.cell(hide_code=True)
def _(mo):
    lookback = mo.ui.slider(3, 52, value=26, label="Trailing calendar weekly changes", show_value=True)
    entry_control = mo.ui.slider(0.0, 1.0, step=0.01, value=0.70, label="Entry agreement", show_value=True)
    exit_control = mo.ui.slider(0.0, 1.0, step=0.01, value=0.65, label="Exit agreement", show_value=True)
    return entry_control, exit_control, lookback


@app.cell
def peer_network_widget(Path, anywidget, mo, traitlets):
    class PeerNetworkWidget(anywidget.AnyWidget):
        _esm = Path(__file__).resolve().with_name("peer_network.mjs")
        payload = traitlets.Dict().tag(sync=True)
        view_state = traitlets.Dict().tag(sync=True)

    peer_network = PeerNetworkWidget()
    peer_network_view = mo.ui.anywidget(peer_network)
    return peer_network, peer_network_view


@app.cell(hide_code=True)
def _(lookback, window_scores):
    prepared_scores = window_scores(lookback.value)
    return (prepared_scores,)


@app.cell(hide_code=True)
def _(
    entry_control,
    exit_control,
    lookback,
    mo,
    np,
    pl,
    prepared_scores,
    replay,
    usable,
):
    mo.stop(exit_control.value > entry_control.value)
    weeks, counts, wins, _scores, active, ages, additions, removals = replay(
        lookback.value, entry_control.value, exit_control.value, prepared_scores, usable
    )
    eligible = counts >= int(np.ceil(0.6 * lookback.value))
    coverage_transitions = np.zeros(len(weeks), dtype=int)
    coverage_transitions[1:] = ((active[1:] != active[:-1]) & (eligible[1:] != eligible[:-1])).sum(axis=1)
    coverage_summary_df = pl.DataFrame(
        {
            "Measure": [
                "Pair-windows with more than one unusable change",
                "Pair-windows below 60% coverage",
                "Displayed link changes involving eligibility reversal",
            ],
            "Count": [
                int((counts < lookback.value - 1).sum()),
                int((~eligible).sum()),
                int(coverage_transitions.sum()),
            ],
            "Denominator": [int(counts.size), int(counts.size), int(additions.sum() + removals.sum())],
        }
    )
    return active, ages, counts, coverage_summary_df, weeks, wins


@app.cell
def weekly_display_layout(item_df, np):
    def weekly_display_layout(item_ids, pair_left, pair_right, active):
        """Deterministic tracking positions, not measured clusters or distances.

        Rows follow chronological snapshots; columns follow the supplied stable item IDs.
        Each week uses only its edges and the previous week's positions/neighbors.
        """
        n = len(item_ids)
        if len(set(item_ids)) != n:
            raise ValueError("Item IDs must be unique")
        categories = item_df["study_category"].to_list()
        names = sorted(set(categories))
        initial = np.empty((n, 2))
        rng = np.random.default_rng(20261121)
        for i, category in enumerate(names):
            members = sorted((j for j in range(n) if categories[j] == category), key=lambda j: item_ids[j])
            angle = 2 * np.pi * i / len(names)
            center = 0.65 * np.array([np.cos(angle), np.sin(angle)])
            radius = 0.16 * np.sqrt(len(members) / 8)
            initial[members] = center + rng.uniform(-radius, radius, (len(members), 2))
        positions = np.empty((len(active), n, 2))
        previous = initial
        previous_edges = np.zeros(active.shape[1], dtype=bool)
        rest = 0.58
        for row, edges in enumerate(active):
            current = previous.copy()
            left, right = pair_left[edges], pair_right[edges]
            degree = np.bincount(np.concatenate((left, right)), minlength=n)
            changed = np.zeros(n, dtype=int)
            changed_pairs = np.flatnonzero(edges != previous_edges)
            np.add.at(changed, pair_left[changed_pairs], 1)
            np.add.at(changed, pair_right[changed_pairs], 1)
            # Stable neighborhoods resist motion; isolated nodes retain their place.
            tether = np.where(degree == 0, 2.0, np.where(changed == 0, 2.0, 0.22))
            for _iteration in range(100 if row == 0 else 24):
                delta = current[:, None, :] - current[None, :, :]
                distance = np.linalg.norm(delta, axis=2)
                safe = np.maximum(distance, 1e-9)
                repulsion = np.maximum(0.28 - distance, 0.0) / safe
                np.fill_diagonal(repulsion, 0.0)
                force = 3.0 * (delta * repulsion[:, :, None]).sum(axis=1)
                if len(left):
                    edge_delta = current[right] - current[left]
                    edge_distance = np.maximum(np.linalg.norm(edge_delta, axis=1), 1e-9)
                    edge_force = edge_delta * ((edge_distance - rest) / edge_distance)[:, None]
                    # Normalize endpoint pull so highly connected hubs cannot dominate.
                    np.add.at(force, left, 0.6 * edge_force / np.maximum(degree[left, None], 1))
                    np.add.at(force, right, -0.6 * edge_force / np.maximum(degree[right, None], 1))
                force -= tether[:, None] * (current - previous) if row else 0
                force -= 1.5 * np.sign(current) * np.maximum(np.abs(current) - 1.0, 0.0)
                current += 0.12 * force
                if row:
                    travel = current - previous
                    lengths = np.linalg.norm(travel, axis=1)
                    current = (
                        previous
                        + travel
                        * np.minimum(1.0, np.where(changed == 0, 0.02, 0.40) * rest / np.maximum(lengths, 1e-9))[
                            :, None
                        ]
                    )
            positions[row] = current
            previous = current
            previous_edges = edges
        return positions

    return (weekly_display_layout,)


@app.cell
def weekly_positions(
    active,
    item_ids,
    pair_left,
    pair_right,
    weekly_display_layout,
):
    weekly_positions = weekly_display_layout(item_ids, pair_left, pair_right, active)
    return (weekly_positions,)


@app.cell
def network_payload(
    active,
    ages,
    counts,
    entry_control,
    item_df,
    item_ids,
    np,
    pair_left,
    pair_right,
    week_dates,
    weekly_positions,
    weeks,
    wins,
):
    # Use a fixed common coordinate frame across rule changes, not per-week scaling.
    _network_weeks = []
    _snapshot_rows = {int(week): row for row, week in enumerate(weeks)}
    for _week_index, _week_date in enumerate(week_dates):
        _row = _snapshot_rows.get(_week_index)
        if _row is None:
            _network_weeks.append({"date": _week_date.isoformat(), "positions": None, "edges": None})
            continue
        _edge_indices = np.flatnonzero(active[_row])
        _network_weeks.append(
            {
                "date": _week_date.isoformat(),
                "positions": np.clip(weekly_positions[_row] / 1.2, -1, 1).tolist(),
                "edges": [
                    {
                        "source": str(item_ids[pair_left[_p]]),
                        "target": str(item_ids[pair_right[_p]]),
                        "wins": int(wins[_row, _p]),
                        "usable": int(counts[_row, _p]),
                        "age": int(ages[_row, _p]),
                    }
                    for _p in _edge_indices
                ],
            }
        )
    network_payload = {
        "entry": float(entry_control.value),
        "nodes": [
            {"id": str(_id), "name": _name, "category": _category}
            for _id, _name, _category in item_df.select("type_id", "type_name", "study_category").iter_rows()
        ],
        "weeks": _network_weeks,
    }
    return (network_payload,)


@app.cell
def update_peer_network(network_payload, peer_network):
    peer_network.payload = network_payload


@app.cell
def peer_network_output(
    entry_control,
    exit_control,
    lookback,
    mo,
    peer_network_view,
):
    mo.vstack(
        [
            mo.accordion({"Network rules": mo.vstack([lookback, entry_control, exit_control])}),
            mo.md("**Exit must not exceed entry. Adjust either cutoff; the network shows the last valid rules.**")
            if exit_control.value > entry_control.value
            else mo.md(""),
            peer_network_view,
        ]
    )


@app.cell(hide_code=True)
def _(coverage_summary_df, mo):
    mo.accordion(
        {
            "Coverage sanity check": mo.vstack(
                [
                    mo.md(
                        "Pair-windows count usable paired changes out of the full lookback, including weeks without an observable peer median. Coverage-involved link changes coincide with a 60% eligibility reversal; other score changes can also reflect missing observations."
                    ),
                    mo.ui.table(coverage_summary_df),
                ]
            )
        }
    )


if __name__ == "__main__":
    app.run()
