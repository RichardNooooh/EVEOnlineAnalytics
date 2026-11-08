"""Plotly views for analysis-ready study-panel data."""

import math

import plotly.express as px
import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

DISPLAY_GROUP_COLORS = {
    "Ships": "#2878B5",
    "Modules": "#E58326",
    "Ammunition and probes": "#38944A",
    "Deployables": "#C84343",
    "Drones": "#8555A6",
    "Minerals": "#555555",
    "Rigs": "#A88A26",
}
CATEGORY_COLORS = {
    "Battleships": "#205A8C",
    "Cruisers and battlecruisers": "#2878B5",
    "Freighters": "#589BC8",
    "Light ships": "#83B8DB",
    "Mining and industrial ships": "#396B87",
    "Defense and repair": "#B85E18",
    "Exploration and resource recovery": "#E58326",
    "Miscellaneous modules": "#EFA65B",
    "Mobility and concealment": "#C87943",
    "Ammunition and probes": "#38944A",
    "Deployables": "#C84343",
    "Drones": "#8555A6",
    "Minerals": "#555555",
    "Rigs": "#A88A26",
}
HISTOGRAM_CATEGORY_GROUPS = {
    "Battleships": "Ships",
    "Cruisers and battlecruisers": "Ships",
    "Freighters": "Ships",
    "Light ships": "Ships",
    "Mining and industrial ships": "Ships",
    "Defense and repair": "Modules",
    "Exploration and resource recovery": "Modules",
    "Miscellaneous modules": "Modules",
    "Mobility and concealment": "Modules",
    "Ammunition and probes": "Ammunition and probes",
    "Deployables": "Deployables",
    "Drones": "Drones",
    "Minerals": "Minerals",
    "Rigs": "Rigs",
}
HISTOGRAM_GROUP_ORDER = [
    "Ships",
    "Modules",
    "Ammunition and probes",
    "Deployables",
    "Drones",
    "Minerals",
    "Rigs",
]


def plot_candidate_relationships(
    activity,
    *,
    fits,
    title,
    x_metric,
    x_label,
    eligibility_minimum,
    eligibility_label,
    specs=None,
):
    """Return a relationship figure without displaying it or mutating ``activity``.

    The Polars frame needs type_id, type_name, total_volume, total_order_count,
    x_metric and each metric in specs. Each panel excludes nonpositive or
    nonfinite x/y values and preserves the remaining input order. No analytical
    statistics are computed here.

    fits maps metric names to dictionaries with n and r (possibly None), and
    optional slope and intercept. These describe log10(y) = intercept + slope *
    log10(x); fitted endpoints use the plotted x range. specs overrides the
    ordered (metric, label, numeric format, color) panels. The other keyword
    options set the title, x axis, and positive eligibility reference line.
    """
    if specs is None:
        specs = [
            ("average_units_per_order", "Average units per order", ",.2f", "#3676a8"),
            ("period_vwap", "Period VWAP (ISK/unit)", ",.2f", "#c97c1d"),
            ("total_estimated_traded_isk", "Estimated traded value (ISK)", ",.0f", "#288779"),
        ]
    series = [
        (
            metric,
            label,
            fmt,
            color,
            activity.filter(
                pl.col(x_metric).cast(pl.Float64).is_finite()
                & (pl.col(x_metric) > 0)
                & pl.col(metric).cast(pl.Float64).is_finite()
                & (pl.col(metric) > 0)
            ),
        )
        for metric, label, fmt, color in specs
    ]
    row_count = len(series)
    plot_height = 300 * row_count + 40 * (row_count - 1)
    x_values = [eligibility_minimum] + [
        value for *_, plotted in series for value in plotted.get_column(x_metric).to_list()
    ]
    log_min, log_max = math.log10(min(x_values)), math.log10(max(x_values))
    padding = max((log_max - log_min) * 0.05, 0.05)
    x_range = [log_min - padding, log_max + padding]
    fig = make_subplots(
        rows=row_count,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=40 / plot_height,
    )
    for row, (metric, label, value_format, color, plotted) in enumerate(series, start=1):
        fig.add_trace(
            go.Scattergl(
                x=plotted.get_column(x_metric).to_list(),
                y=plotted.get_column(metric).to_list(),
                mode="markers",
                marker={"color": color, "size": 7, "opacity": 0.65},
                customdata=plotted.select(
                    "type_name",
                    "type_id",
                    "total_volume",
                    "total_order_count",
                ).rows(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b> (type %{customdata[1]})<br>"
                    + f"{x_label}: %{{x:,.4g}}<br>"
                    + "Total history order count: %{customdata[3]:,.0f}<br>"
                    + ("Total volume: %{customdata[2]:,.0f}<br>" if row == 1 else "")
                    + f"{label}: %{{y:{value_format}}}<extra></extra>"
                ),
                showlegend=False,
            ),
            row=row,
            col=1,
        )
        if metric in fits:
            fit = fits[metric]
            endpoints = []
            fitted = []
            if plotted.height and fit.get("slope") is not None and fit.get("intercept") is not None:
                xs = plotted.get_column(x_metric).to_list()
                endpoints = [min(xs), max(xs)]
                try:
                    fitted = [10 ** (fit["intercept"] + fit["slope"] * math.log10(x)) for x in endpoints]
                except OverflowError:
                    fitted = []
            if len(fitted) == 2 and all(math.isfinite(y) and y > 0 for y in fitted):
                fig.add_trace(
                    go.Scatter(
                        x=endpoints,
                        y=fitted,
                        mode="lines",
                        line={"color": color, "width": 1, "dash": "solid"},
                        hoverinfo="skip",
                        showlegend=False,
                    ),
                    row=row,
                    col=1,
                )
            correlation = f"{fit['r']:.3f}" if fit["r"] is not None else "unavailable"
            fig.add_annotation(
                text=f"Log Pearson r = {correlation}; n = {fit['n']}",
                x=0.99,
                y=0.98,
                xref="x domain",
                yref="y domain",
                xanchor="right",
                yanchor="top",
                showarrow=False,
                row=row,
                col=1,
            )
        # Anchor the real shared axis at the bottom for native hover placement.
        # Overlay axes supply only the upper rows' ticks, without empty hover panels.
        tick_row = row_count if row == 1 else row - 1
        tick_anchor = "y" if tick_row == 1 else f"y{tick_row}"
        fig.update_xaxes(
            type="log",
            range=x_range,
            showticklabels=True,
            tickmode="auto",
            anchor=tick_anchor,
            matches="x" if row > 1 else None,
            overlaying="x" if row > 1 else None,
            title=x_label if row == 1 else None,
            row=row,
            col=1,
        )
        fig.update_yaxes(type="log", title=label, anchor="x", row=row, col=1)
        fig.add_vline(x=eligibility_minimum, line_dash="dash", line_color="#777777", row=row, col=1)

    # Cross-panel hover needs the same trace axis, not only matched ranges.
    fig.update_traces(xaxis="x")
    fig.add_annotation(
        text=eligibility_label,
        x=0,
        y=1.025,
        xref="paper",
        yref="paper",
        xanchor="left",
        showarrow=False,
    )
    fig.update_layout(
        title=title,
        width=1300,
        height=plot_height + 155,
        hovermode="closest",
        hoverlabel={"showarrow": True},
        margin={"t": 75, "r": 20, "b": 80, "l": 75},
    )
    return fig


def plot_activity_distribution(
    activity,
    *,
    metric,
    cutoff,
    cutoff_text,
    top_n,
    title,
    x_label,
    y_label,
    unit,
    color,
    eligibility_column=None,
):
    """Return an ECDF figure without display or input mutation.

    activity needs type_id, type_name and metric, plus eligibility_column when
    supplied. That column's non-null rows are eligible; only positive finite
    metric values are plotted and constitute the percentage denominator. Plotly
    orders the ECDF by metric. cutoff must be positive and finite; cutoff_text,
    top_n and unit label it, while title, x_label, y_label and color style the
    figure. An empty positive population or invalid cutoff raises ValueError.
    """
    eligible = activity.filter(pl.col(eligibility_column).is_not_null()) if eligibility_column else activity
    positive = eligible.with_columns(pl.col(metric).cast(pl.Float64)).filter(
        pl.col(metric).is_finite() & (pl.col(metric) > 0)
    )
    if positive.is_empty() or cutoff is None or not math.isfinite(cutoff) or cutoff <= 0:
        raise ValueError(f"No positive finite totals or selected cutoff for {title}.")
    fig = px.ecdf(
        positive,
        x=metric,
        ecdfnorm="percent",
        log_x=True,
        color_discrete_sequence=[color],
        hover_data=["type_id", "type_name"],
        title=title,
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[1]}</b> (type %{customdata[0]})<br>"
            + f"{x_label}: %{{x:,.0f}}<br>"
            + f"{y_label}: %{{y:.2f}}<extra></extra>"
        )
    )
    fig.add_shape(
        type="line",
        x0=cutoff,
        x1=cutoff,
        y0=0,
        y1=1,
        xref="x",
        yref="y domain",
        line={"dash": "dash", "color": "#4d4d4d", "width": 2},
    )
    fig.add_annotation(
        x=math.log10(cutoff),
        y=20,
        xref="x",
        yref="y",
        text=f"Top-{top_n} cutoff<br>{cutoff_text}",
        showarrow=False,
        hovertext=f"Top-{top_n} cutoff: {cutoff:,.0f} {unit}",
        captureevents=True,
        xanchor="right",
        yanchor="top",
        font={"color": "white"},
        bgcolor="#4d4d4d",
        bordercolor="white",
        borderwidth=1,
    )
    fig.update_xaxes(title=x_label, exponentformat="B")
    fig.update_yaxes(title=y_label, range=[0, 102])
    fig.update_layout(height=450, width=1200, showlegend=False)
    return fig


def plot_activity_ranking(chart_data, *, metric, title, x_label, color):
    """Return a ranking figure without display or input mutation.

    chart_data needs type_id, type_name, metric, order_count_rank and
    estimated_traded_isk_rank. Supply the already selected rows in rank order;
    no filtering or ranking is performed. Keywords choose the metric, title,
    axis label and color. Missing names receive a display-only fallback.
    """
    chart_data = chart_data.with_columns(
        pl.concat_str(
            [
                pl.col("type_name").fill_null("Name unavailable"),
                pl.lit(" ["),
                pl.col("type_id").cast(pl.String),
                pl.lit("]"),
            ]
        ).alias("label")
    )
    fig = px.bar(
        chart_data,
        x=metric,
        y="label",
        orientation="h",
        color_discrete_sequence=[color],
        hover_data={
            "type_id": True,
            "type_name": True,
            "order_count_rank": True,
            "estimated_traded_isk_rank": True,
            metric: ":,.0f",
        },
        title=title,
    )
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title=x_label, rangemode="tozero", exponentformat="B")
    fig.update_layout(height=max(500, chart_data.height * 27), width=1200, showlegend=False)
    return fig


def plot_ranked_selection_overlap(counts, *, curated_only_count, title, x_label, colors=None):
    """Return an overlap figure without display or input mutation.

    counts has label and count columns, one row per disjoint segment in display
    order. Shares use the sum of counts (the ranked union), excluding the
    separately annotated curated_only_count. A zero total raises ValueError.
    title and x_label set labels; colors optionally maps segment labels to
    colors, defaulting to the notebook's three ranked-overlap colors.
    """
    colors = colors or {"Order-only": "#3676a8", "Both": "#7a5195", "ISK-only": "#288779"}
    total = counts.get_column("count").sum()
    if not total:
        raise ValueError("The ranked-selection union is empty.")
    segments = [
        (row["label"], row["count"], row["count"] / total, colors[row["label"]]) for row in counts.iter_rows(named=True)
    ]
    fig = go.Figure()
    for label, count, share, color in segments:
        fig.add_trace(
            go.Bar(
                y=[""],
                x=[count],
                name=label,
                orientation="h",
                marker_color=color,
                text=[f"{count:,} ({share:.1%})"],
                textposition="inside",
                insidetextanchor="middle",
                hovertemplate=(f"{label}<br>{count:,} items<br>{share:.1%} of unique ranked union<extra></extra>"),
            )
        )
    fig.update_layout(
        title=f"{title}<br><sup>Curated-only additions: {curated_only_count:,}</sup>",
        barmode="stack",
        xaxis_title=x_label,
        yaxis_title=None,
        width=750,
        height=240,
        margin={"t": 65, "b": 75, "l": 20, "r": 20},
        legend={"title_text": "", "orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.5, "yanchor": "top"},
    )
    fig.update_yaxes(showticklabels=False)
    return fig


def plot_monthly_history_availability(
    coverage,
    *,
    colorscale="Blues",
    title="Monthly market-history availability",
    x_label="Month",
    colorbar_label="Recorded days (%)",
):
    """Return a coverage heatmap without display or input mutation.

    coverage needs type_id, type_name, month, recorded_day_count,
    expected_day_count and recorded_day_pct, with exactly one row per item and
    month in a complete rectangular grid and a consistent name per item. Item
    order follows first appearance; months are sorted. Percentages and their
    calendar-day denominators must already be calculated. Keywords override
    the colorscale, title, x-axis label and colorbar label.
    """
    items = coverage.select("type_id", "type_name").unique(maintain_order=True).rows()
    months = coverage.get_column("month").unique().sort().to_list()
    lookup = {(r["type_id"], r["month"]): r for r in coverage.iter_rows(named=True)}
    if len(lookup) != coverage.height or len(lookup) != len(items) * len(months):
        raise ValueError("Coverage must contain exactly one row per item-month.")
    labels = [f"{name if name is not None else 'Name unavailable'} [{type_id}]" for type_id, name in items]
    percentages = [[lookup[(type_id, month)]["recorded_day_pct"] for month in months] for type_id, _ in items]
    recorded_expected_days = [
        [
            [lookup[(type_id, month)]["recorded_day_count"], lookup[(type_id, month)]["expected_day_count"]]
            for month in months
        ]
        for type_id, _ in items
    ]
    fig = go.Figure(
        go.Heatmap(
            z=percentages,
            x=months,
            y=labels,
            customdata=recorded_expected_days,
            colorscale=colorscale,
            zmin=0,
            zmax=100,
            colorbar={"title": colorbar_label},
            hovertemplate=(
                "<b>%{y}</b><br>%{x|%Y-%m}<br>"
                "%{customdata[0]:.0f} of %{customdata[1]:.0f} days recorded — %{z:.1f}%"
                "<extra></extra>"
            ),
        )
    )
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(dtick="M3", tickformat="%Y-%m", tickangle=-45, title=x_label)
    fig.update_layout(height=max(600, len(labels) * 22), width=1000, title=title)
    return fig


def _metric_value_status(value):
    if value is None:
        return "missing"
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "nonfinite_invalid"
    if not math.isfinite(numeric_value):
        return "nonfinite_invalid"
    if numeric_value < 0:
        return "finite_invalid"
    if numeric_value == 0:
        return "zero"
    return "positive"


def _log_histogram_summary(history, value_column, *, category_groups, group_order, bin_count):
    group_values = {group: [] for group in group_order}
    group_statuses = {
        group: dict.fromkeys(("positive", "zero", "missing", "finite_invalid", "nonfinite_invalid"), 0)
        for group in group_order
    }
    for row in history.select("study_category", value_column).iter_rows(named=True):
        category = row["study_category"]
        try:
            group = category_groups[category]
        except KeyError as error:
            raise ValueError(f"Unknown histogram display category: {category}") from error
        status = _metric_value_status(row[value_column])
        group_statuses[group][status] += 1
        if status == "positive":
            group_values[group].append(float(row[value_column]))

    all_positive = [value for values in group_values.values() for value in values]
    if all_positive:
        log_min, log_max = math.log10(min(all_positive)), math.log10(max(all_positive))
        if math.isclose(log_min, log_max):
            log_min -= 0.5
            log_max += 0.5
    else:
        log_min, log_max = -0.5, 0.5
    log_edges = [log_min + (log_max - log_min) * step / bin_count for step in range(bin_count + 1)]
    bin_edges = [10**edge for edge in log_edges]

    histogram_rows = []
    for group, values in group_values.items():
        counts = [0] * bin_count
        for value in values:
            bin_index = min(bin_count - 1, max(0, int((math.log10(value) - log_min) / (log_max - log_min) * bin_count)))
            counts[bin_index] += 1
        total = sum(group_statuses[group].values())
        for bin_index, count in enumerate(counts):
            if count or not values:
                histogram_rows.append(
                    {
                        "histogram_group": group,
                        "bin_left": bin_edges[bin_index],
                        "bin_right": bin_edges[bin_index + 1],
                        "bin_center": math.sqrt(bin_edges[bin_index] * bin_edges[bin_index + 1]),
                        "count": count,
                        "percent_within_group": 0 if not values else count / len(values) * 100,
                        "positive_count": len(values),
                        "calendar_item_days": total,
                        "zero_count": group_statuses[group]["zero"],
                        "missing_count": group_statuses[group]["missing"],
                        "finite_invalid_count": group_statuses[group]["finite_invalid"],
                        "nonfinite_invalid_count": group_statuses[group]["nonfinite_invalid"],
                    }
                )
                if not values:
                    break
    return pl.DataFrame(histogram_rows), bin_edges


def plot_retained_distributions(
    history,
    *,
    specs=None,
    group_order=None,
    group_colors=None,
    category_groups=None,
    bin_count=30,
    title="Daily market distributions by group",
    y_label="Within-group share (%)",
):
    """Return retained-history histograms without display or input mutation.

    history is calendar-completed item-day data with study_category and the
    metric columns in specs. Default metrics are vwap, volume, order_count and
    the precomputed relative_daily_high_low_dispersion. Only positive finite
    values enter log bins; percentages are normalized by positive finite values
    in each group. Hover status counts use all calendar item-days, including
    zero, missing, negative and nonfinite values.

    specs supplies ordered (column, axis title) pairs for the four panels;
    category_groups maps categories to groups, group_order controls trace order,
    and group_colors maps groups to colors. bin_count controls common log bins;
    title and y_label set labels. Defaults reproduce the notebook view.
    """
    if specs is None:
        specs = [
            ("vwap", "Daily VWAP (ISK/unit)"),
            ("volume", "Daily traded volume (units)"),
            ("order_count", "Daily history order count"),
            ("relative_daily_high_low_dispersion", "Relative daily price range: (high − low) / VWAP"),  # noqa: RUF001
        ]
    group_order = HISTOGRAM_GROUP_ORDER if group_order is None else group_order
    group_colors = DISPLAY_GROUP_COLORS if group_colors is None else group_colors
    category_groups = HISTOGRAM_CATEGORY_GROUPS if category_groups is None else category_groups
    if bin_count <= 0:
        raise ValueError("bin_count must be positive")
    summaries = {
        metric: _log_histogram_summary(
            history, metric, category_groups=category_groups, group_order=group_order, bin_count=bin_count
        )
        for metric, _ in specs
    }
    fig = make_subplots(
        rows=2,
        cols=2,
        horizontal_spacing=0.08,
        vertical_spacing=0.10,
    )

    for metric_index, (value_column, axis_title) in enumerate(specs):
        row, col = divmod(metric_index, 2)
        histogram, _ = summaries[value_column]
        status_summaries = []
        for group in group_order:
            group_histogram = histogram.filter(pl.col("histogram_group") == group).sort("bin_center")
            if group_histogram.is_empty():
                continue
            status = group_histogram.row(0, named=True)
            if status["positive_count"] == 0:
                status_summaries.append(
                    f"{group}: 0 positive; {status['zero_count']} zero; {status['missing_count']} missing"
                )
                fig.add_trace(
                    go.Scatter(
                        x=[1],
                        y=[0],
                        mode="markers",
                        name=group,
                        legendgroup=group,
                        showlegend=metric_index == 0,
                        marker={
                            "color": group_colors[group],
                            "size": 9,
                            "symbol": "circle-open",
                            "line": {"color": group_colors[group], "width": 1},
                        },
                        customdata=[
                            (
                                status["calendar_item_days"],
                                status["zero_count"],
                                status["missing_count"],
                                status["finite_invalid_count"],
                                status["nonfinite_invalid_count"],
                            )
                        ],
                        hovertemplate=(
                            "<b>%{fullData.name}</b><br>No positive finite values"
                            "<br>Calendar item-days: %{customdata[0]}"
                            "<br>Zero: %{customdata[1]}"
                            "<br>Missing: %{customdata[2]}"
                            "<br>Finite invalid: %{customdata[3]}"
                            "<br>Non-finite invalid: %{customdata[4]}<extra></extra>"
                        ),
                    ),
                    row=row + 1,
                    col=col + 1,
                )
                continue
            bin_left = group_histogram.get_column("bin_left")
            bin_right = group_histogram.get_column("bin_right")
            customdata = [
                (
                    bin_row["bin_left"],
                    bin_row["bin_right"],
                    bin_row["count"],
                    bin_row["positive_count"],
                    bin_row["calendar_item_days"],
                    bin_row["zero_count"],
                    bin_row["zero_count"] / bin_row["calendar_item_days"] * 100,
                    bin_row["missing_count"],
                    bin_row["missing_count"] / bin_row["calendar_item_days"] * 100,
                    bin_row["finite_invalid_count"],
                    bin_row["nonfinite_invalid_count"],
                )
                for bin_row in group_histogram.iter_rows(named=True)
            ]
            fig.add_trace(
                go.Bar(
                    x=(bin_left + bin_right) / 2,
                    y=group_histogram.get_column("percent_within_group"),
                    width=bin_right - bin_left,
                    name=group,
                    legendgroup=group,
                    showlegend=metric_index == 0,
                    marker={
                        "color": group_colors[group],
                        "line": {"color": group_colors[group], "width": 0.75},
                    },
                    opacity=0.48,
                    customdata=customdata,
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>Bin left: %{customdata[0]:.4g}"
                        "<br>Bin right: %{customdata[1]:.4g}"
                        "<br>Positive finite values in bin: %{customdata[2]}"
                        "<br>Share of positive finite group values: %{y:.2f}%"
                        "<br>Positive finite: %{customdata[3]} of %{customdata[4]} item-days"
                        "<br>Zero: %{customdata[5]} (%{customdata[6]:.2f}%)"
                        "<br>Missing: %{customdata[7]} (%{customdata[8]:.2f}%)"
                        "<br>Finite invalid: %{customdata[9]}"
                        "<br>Non-finite invalid: %{customdata[10]}<extra></extra>"
                    ),
                ),
                row=row + 1,
                col=col + 1,
            )
        if status_summaries:
            fig.add_annotation(
                text="<br>".join(status_summaries),
                xref=f"x{metric_index + 1} domain" if metric_index else "x domain",
                yref=f"y{metric_index + 1} domain" if metric_index else "y domain",
                x=0.01,
                y=0.99,
                xanchor="left",
                yanchor="top",
                align="left",
                showarrow=False,
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="rgba(0,0,0,0.2)",
                borderwidth=1,
                font={"size": 10},
            )
        fig.update_xaxes(type="log", title_text=axis_title, row=row + 1, col=col + 1)
        fig.update_yaxes(title_text=y_label if col == 0 else None, row=row + 1, col=col + 1)

    fig.update_layout(
        title={
            "text": title,
            "x": 0.5,
            "xanchor": "center",
            "y": 0.98,
            "yanchor": "top",
        },
        barmode="overlay",
        width=1200,
        height=960,
        legend={
            "groupclick": "togglegroup",
            "itemclick": "toggle",
            "itemdoubleclick": "toggleothers",
            "orientation": "h",
            "y": 1.02,
            "yanchor": "bottom",
        },
        margin={"l": 70, "r": 30, "t": 110, "b": 70},
    )
    return fig


def plot_retained_composition(
    composition,
    *,
    colors,
    title,
    panel_titles,
    x_label,
):
    """Return a composition figure without display or input mutation.

    composition needs study_category, retained_item_count,
    selection_estimated_traded_isk, selection_order_count, and their precomputed
    share columns retained_item_share_pct,
    selection_estimated_traded_isk_share_pct and selection_order_count_share_pct.
    Shares use the corresponding all-category totals as denominators. Rows are
    plotted in input order without filtering or recomputing shares. colors maps
    categories to colors; title, three panel_titles and x_label set labels.
    """
    fig = make_subplots(
        rows=1,
        cols=3,
        shared_yaxes=True,
        subplot_titles=panel_titles,
        horizontal_spacing=0.08,
    )
    for column, label, subplot_column in [
        ("retained_item_share_pct", "Retained-item share", 1),
        (
            "selection_estimated_traded_isk_share_pct",
            "Selection-period estimated traded ISK share",
            2,
        ),
        ("selection_order_count_share_pct", "Selection-period history order count share", 3),
    ]:
        fig.add_trace(
            go.Bar(
                x=composition.get_column(column),
                y=composition.get_column("study_category"),
                orientation="h",
                marker={"color": [colors[category] for category in composition.get_column("study_category")]},
                customdata=composition.select(
                    "retained_item_count", "selection_estimated_traded_isk", "selection_order_count"
                ).rows(),
                hovertemplate=(
                    "<b>%{y}</b><br>Share: %{x:.2f}%"
                    "<br>Retained items: %{customdata[0]}"
                    "<br>Selection-period estimated traded ISK: %{customdata[1]:,.0f}"
                    "<br>Selection-period history order count: %{customdata[2]:,.0f}"
                    "<extra></extra>"
                ),
                showlegend=False,
                name=label,
            ),
            row=1,
            col=subplot_column,
        )
        fig.update_xaxes(title_text=x_label, ticksuffix="%", row=1, col=subplot_column)

    fig.update_yaxes(showticklabels=False, row=1, col=2)
    fig.update_yaxes(showticklabels=False, row=1, col=3)
    fig.update_layout(
        title=title,
        width=1200,
        height=max(550, 35 * composition.height + 180),
        margin={"l": 250, "r": 40, "t": 100, "b": 70},
    )
    return fig
