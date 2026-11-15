"""Preparation of the existing PCA projection for temporal display.

The input coordinates are already fitted PCA scores. This module does not fit or
transform any observations.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from IPython.display import HTML


def prepare_temporal_pca(prepared):
    """Build chronological display indexes without changing the supplied data."""
    coordinates = np.asarray(prepared["coordinates"])
    dates = np.asarray(prepared["dates"], dtype="datetime64[D]")
    if coordinates.ndim != 2 or coordinates.shape != (len(dates), 3) or not len(dates):
        raise ValueError("Expected nonempty, aligned three-dimensional PCA coordinates and dates.")
    if not np.isfinite(coordinates).all() or np.isnat(dates).any():
        raise ValueError("PCA coordinates and dates must be finite.")

    step = prepared.get("expected_step_days", 1)
    if isinstance(step, bool) or not isinstance(step, (int, np.integer)) or step < 1:
        raise ValueError("expected_step_days must be a positive integer.")
    categories = prepared.get("study_categories")
    palette = prepared.get("category_colors")
    if (categories is None) != (palette is None):
        raise ValueError("study_categories and category_colors must be supplied together.")
    if categories is not None:
        categories = np.asarray(categories, dtype=object)
        if categories.shape != (len(dates),) or any(not isinstance(c, str) or not c for c in categories):
            raise ValueError("study_categories must contain an aligned nonempty name for each observation.")
        if (
            not isinstance(palette, dict)
            or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in palette.items())
            or any(c not in palette for c in categories)
        ):
            raise ValueError("category_colors must map every study category to a CSS color string.")
        categories = categories.tolist()
        palette = dict(palette)
    week_starts = prepared.get("week_starts")
    if week_starts is not None:
        week_starts = np.asarray(week_starts, dtype="datetime64[D]")
        if week_starts.shape != dates.shape or np.isnat(week_starts).any() or np.any(week_starts > dates):
            raise ValueError("week_starts must contain aligned valid dates no later than dates.")
        week_starts = np.datetime_as_string(week_starts, unit="D").tolist()

    first = dates.min()
    days = (dates - first).astype(np.int64)
    groups = []
    ids = set()
    row_item = np.full(len(dates), -1, dtype=np.int64)
    for index, (type_id, name, rows) in enumerate(
        zip(prepared["type_ids"], prepared["labels"], prepared["group_rows"], strict=True)
    ):
        if int(type_id) in ids:
            raise ValueError("Item IDs must be unique.")
        ids.add(int(type_id))
        rows = np.asarray(rows, dtype=np.int64)
        if np.any(rows < 0) or np.any(rows >= len(dates)) or len(np.unique(rows)) != len(rows):
            raise ValueError("Item row indexes must be distinct valid rows.")
        if np.any(row_item[rows] != -1):
            raise ValueError("Item row indexes must not overlap.")
        row_item[rows] = index
        rows = rows[np.argsort(days[rows], kind="stable")]
        if len(np.unique(days[rows])) != len(rows):
            raise ValueError("Item dates must be unique.")
        groups.append(
            {
                "id": int(type_id),
                "name": str(name),
                "rows": rows.tolist(),
                "days": days[rows].tolist(),
                "adjacent": np.concatenate(([False], np.diff(days[rows]) == step)).tolist() if len(rows) else [],
            }
        )
    if np.any(row_item == -1):
        raise ValueError("Every observation must belong to exactly one item.")
    central = np.asarray(prepared["central_ranges"], dtype=float)
    if central.shape != (3, 2) or not np.isfinite(central).all() or np.any(central[:, 0] > central[:, 1]):
        raise ValueError("Central ranges must contain three ordered finite bounds.")
    clipped = np.any((coordinates < central[:, 0]) | (coordinates > central[:, 1]), axis=1)
    for group in groups:
        group["clipped_prefix"] = np.concatenate(([0], np.cumsum(clipped[group["rows"]]))).tolist()
    full = []
    for column in coordinates.T:
        low, high = float(column.min()), float(column.max())
        pad = (high - low) * 0.03 or 1.0
        full.append([low - pad, high + pad])
    return {
        "coordinates": coordinates.copy(),
        "days": days,
        "first_date": str(first),
        "last_day": int(days.max()),
        "items": groups,
        "row_item": row_item,
        "full_ranges": full,
        "central_ranges": central.tolist(),
        "central_clipped": clipped,
        "date_labels": np.datetime_as_string(dates, unit="D").tolist(),
        "week_starts": week_starts,
        "study_categories": categories,
        "category_colors": palette,
        "expected_step_days": int(step),
    }


def build_temporal_pca_figure(model, *, title="PCA over time"):
    """Build a figure with a resident full-history context and interactive layers."""
    coords = model["coordinates"]
    figure = go.Figure()
    figure.add_trace(
        go.Scatter3d(
            x=coords[:, 0].tolist(),
            y=coords[:, 1].tolist(),
            z=coords[:, 2].tolist(),
            mode="markers",
            marker={"size": 2, "color": "#808080", "opacity": 0.12},
            hoverinfo="skip",
            showlegend=False,
            name="Full history",
        )
    )
    figure.add_trace(
        go.Scatter3d(
            x=[],
            y=[],
            z=[],
            mode="markers",
            name="Selected observations",
            showlegend=False,
            marker={
                "size": 4,
                "color": [],
                "colorscale": "Viridis",
                "showscale": True,
                "colorbar": {"title": {"text": "Date"}, "len": 0.7},
            },
            hovertemplate="%{text}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter3d(
            x=[],
            y=[],
            z=[],
            mode="lines",
            line={"color": "#444", "width": 4},
            hoverinfo="skip",
            showlegend=False,
            name="Trajectory",
        )
    )
    for name, color, symbol in (("First", "#1b9e77", "diamond"), ("Last", "#d95f02", "square")):
        figure.add_trace(
            go.Scatter3d(
                x=[],
                y=[],
                z=[],
                mode="markers",
                name=name,
                marker={"size": 10 if name == "First" else 7, "color": color, "symbol": symbol},
                hovertemplate="%{text}<extra></extra>",
            )
        )
    figure.update_layout(
        title=title,
        height=700,
        uirevision="temporal-pca",
        margin={"l": 0, "r": 0, "t": 55, "b": 0},
        legend={"orientation": "h", "x": 0, "y": 1.02},
        scene={
            "aspectmode": "cube",
            "xaxis": {"title": "PC1", "range": model["full_ranges"][0]},
            "yaxis": {"title": "PC2", "range": model["full_ranges"][1]},
            "zaxis": {"title": "PC3", "range": model["full_ranges"][2]},
        },
    )
    return figure


def temporal_pca_html(figure, model):
    """Return a self-contained fragment with per-instance controls and state."""
    browser = {
        key: model[key]
        for key in (
            "items",
            "first_date",
            "last_day",
            "date_labels",
            "full_ranges",
            "central_ranges",
            "week_starts",
            "study_categories",
            "category_colors",
        )
    }
    script = Path(__file__).with_name("temporal_pca.js").read_text(encoding="utf-8")
    script = script.replace("__TEMPORAL_PCA_MODEL__", json.dumps(browser, separators=(",", ":")).replace("</", "<\\/"))
    return pio.to_html(
        figure,
        full_html=False,
        include_plotlyjs=True,
        post_script=script,
        config={"responsive": True, "doubleClick": False},
    )


def plot_temporal_pca(prepared, *, title="PCA over time"):
    """Return the offline interactive view as an IPython HTML object."""
    model = prepare_temporal_pca(prepared)
    return HTML(temporal_pca_html(build_temporal_pca_figure(model, title=title), model))
