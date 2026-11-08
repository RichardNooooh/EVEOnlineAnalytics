"""Interactive production-relationship graph helpers for the frozen Forge study panel."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import plotly.graph_objects as go
import plotly.io as pio

INTERACTION_SCRIPT_PATH = Path(__file__).with_name("production_graph.js")


def _interaction_script(browser_model):
    """Load the repository-bundled interaction script and embed its graph payload."""
    script = INTERACTION_SCRIPT_PATH.read_text(encoding="utf-8")
    return script.replace("__PRODUCTION_GRAPH_MODEL__", json.dumps(browser_model, separators=(",", ":")))


def prepare_production_graph(links, panel_items, reference_types, meta_groups, mineral_ids, category_palette):
    """Prepare retained records using the supplied palette for every panel category."""
    panel_rows = (
        panel_items.select("type_id", "type_name", "study_category").unique("type_id").sort("type_id").to_dicts()
    )
    panel_ids = {row["type_id"] for row in panel_rows}
    mineral_ids = set(mineral_ids)
    if not mineral_ids.issubset(panel_ids):
        raise ValueError("The graph requires every curated mineral in the study panel.")

    panel_names = {row["type_id"]: row["type_name"] for row in panel_rows}
    reference_names = {
        int(type_id): record["name"]["en"]
        for type_id, record in reference_types.items()
        if isinstance(record, dict) and isinstance(record.get("name"), dict) and record["name"].get("en")
    }
    type_names = {**panel_names, **reference_names}

    def type_name(type_id):
        return type_names.get(type_id, f"Type ID {type_id}")

    classifications = {}
    for type_id, record in reference_types.items():
        if not isinstance(record, dict):
            continue
        meta_group_id = record.get("meta_group_id")
        group = meta_groups.get(str(meta_group_id)) if isinstance(meta_group_id, int) else None
        group_name = (
            group.get("name", {}).get("en") if isinstance(group, dict) and isinstance(group.get("name"), dict) else None
        )
        classifications[int(type_id)] = group_name or "Unclassified"

    def classification(type_id):
        return classifications.get(type_id, "Unclassified")

    link_rows = (
        links.select("input_type_id", "output_type_id").unique().sort(["input_type_id", "output_type_id"]).to_dicts()
    )
    non_mineral_panel_ids = panel_ids - mineral_ids
    external_inputs = {
        row["input_type_id"]
        for row in link_rows
        if row["input_type_id"] not in panel_ids and row["output_type_id"] in panel_ids
    }
    aggregate_products = {}
    for row in link_rows:
        input_id, output_id = row["input_type_id"], row["output_type_id"]
        if input_id in non_mineral_panel_ids and output_id not in panel_ids:
            aggregate_products.setdefault((input_id, classification(output_id)), set()).add(output_id)

    categories = sorted({row["study_category"] for row in panel_rows if row["type_id"] not in mineral_ids})
    category_colors = {category: category_palette[category] for category in categories}
    nodes = [
        {
            "id": f"panel:{row['type_id']}",
            "type_id": row["type_id"],
            "name": type_name(row["type_id"]),
            "role": "mineral" if row["type_id"] in mineral_ids else "panel",
            "category": row["study_category"],
            "color": category_palette[row["study_category"]],
        }
        for row in panel_rows
    ]
    nodes.extend(
        {
            "id": f"input:{type_id}",
            "type_id": type_id,
            "name": type_name(type_id),
            "role": "external_input",
            "category": None,
            "color": "#c5c7ca",
        }
        for type_id in sorted(external_inputs)
    )
    group_names = sorted({group_name for _input_id, group_name in aggregate_products})
    nodes.extend(
        {
            "id": f"group:{group_name}",
            "type_id": None,
            "name": group_name,
            "role": "external_group",
            "category": None,
            "color": "#c5c7ca",
        }
        for group_name in group_names
    )

    edges = []
    for row in link_rows:
        input_id, output_id = row["input_type_id"], row["output_type_id"]
        if input_id in panel_ids and output_id in panel_ids:
            edges.append(
                {"source": f"panel:{input_id}", "target": f"panel:{output_id}", "kind": "internal", "products": []}
            )
        elif input_id in external_inputs and output_id in panel_ids:
            edges.append(
                {"source": f"input:{input_id}", "target": f"panel:{output_id}", "kind": "upstream", "products": []}
            )
    for (input_id, group_name), product_ids in sorted(aggregate_products.items()):
        products = [{"id": product_id, "name": type_name(product_id)} for product_id in sorted(product_ids)]
        edges.append(
            {
                "source": f"panel:{input_id}",
                "target": f"group:{group_name}",
                "kind": "aggregate",
                "products": products,
                "product_label": "<br>".join(product["name"] for product in products),
            }
        )

    node_by_id = {node["id"]: node for node in nodes}
    incident_edges = {node_id: [] for node_id in node_by_id}
    for edge_index, edge in enumerate(edges):
        incident_edges[edge["source"]].append(edge_index)
        incident_edges[edge["target"]].append(edge_index)
    return {
        "nodes": nodes,
        "edges": edges,
        "node_by_id": node_by_id,
        "incident_edges": incident_edges,
        "type_names": type_names,
        "classifications": classifications,
        "category_colors": category_colors,
    }


def layout_production_graph(model, layout_seed=17):
    """Pack deterministic oval clouds; category forces are layout-only, never data edges."""
    regions = {
        "mineral": (-5.8, -2.6, 2.2, 4.2),
        "external_input": (-6.1, -2.8, -3.9, -1.1),
        "panel": (-2.0, 2.6, -3.5, 1.9),
        "external_group": (3.5, 5.8, -1.5, 0.6),
    }
    graph = nx.Graph()
    graph.add_nodes_from(model["node_by_id"])
    graph.add_edges_from((edge["source"], edge["target"]) for edge in model["edges"])
    raw_positions = nx.spring_layout(graph, seed=layout_seed, weight=None, iterations=150)
    positions = {}
    for role, bounds in regions.items():
        members = sorted(node["id"] for node in model["nodes"] if node["role"] == role)
        if not members:
            continue
        x0, x1, y0, y1 = bounds
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
        raw_x = [float(raw_positions[node_id][0]) for node_id in members]
        raw_y = [float(raw_positions[node_id][1]) for node_id in members]
        mean_x, mean_y = sum(raw_x) / len(members), sum(raw_y) / len(members)
        span = max(max(raw_x) - min(raw_x), max(raw_y) - min(raw_y), 1e-9)
        xs = [cx + (value - mean_x) / span * rx for value in raw_x]
        ys = [cy + (value - mean_y) / span * ry for value in raw_y]
        # Reserve packing slack inside the oval, including room for its curved boundary.
        # Label clouds reserve horizontal name space as well as marker clearance.
        minimum = min(0.60 if role == "panel" else 0.50, (rx * ry * 3.14 / len(members)) ** 0.5 * 0.95)
        label_width = 1.55 if role in {"mineral", "external_group"} else minimum
        label_height = 0.46 if role in {"mineral", "external_group"} else minimum
        categories = {}
        if role == "panel":
            for index, node_id in enumerate(members):
                categories.setdefault(model["node_by_id"][node_id]["category"], []).append(index)
        for iteration in range(320):
            # Finish with separation only: attraction must not leave touching markers.
            attraction = 1 if iteration < 240 else 0
            xs = [value + (cx - value) * 0.008 * attraction for value in xs]
            ys = [value + (cy - value) * 0.008 * attraction for value in ys]
            # Category cohesion forms loose neighborhoods inside the shared cloud.
            for indices in categories.values():
                center_x = sum(xs[index] for index in indices) / len(indices)
                center_y = sum(ys[index] for index in indices) / len(indices)
                for index in indices:
                    xs[index] += (center_x - xs[index]) * 0.10 * attraction
                    ys[index] += (center_y - ys[index]) * 0.10 * attraction
            for left in range(len(members)):
                for right in range(left + 1, len(members)):
                    dx, dy = xs[right] - xs[left], ys[right] - ys[left]
                    distance = ((dx / label_width) ** 2 + (dy / label_height) ** 2) ** 0.5
                    if distance >= 1:
                        continue
                    if distance < 1e-9:
                        dx = 1.0 if members[left] < members[right] else -1.0
                        dy = 0.5
                        distance = ((dx / label_width) ** 2 + (dy / label_height) ** 2) ** 0.5
                    shift = (1 - distance) / (2 * distance)
                    xs[left] -= dx * shift
                    ys[left] -= dy * shift
                    xs[right] += dx * shift
                    ys[right] += dy * shift
            for index in range(len(members)):
                radius = (((xs[index] - cx) / rx) ** 2 + ((ys[index] - cy) / ry) ** 2) ** 0.5
                if radius > 0.94:
                    xs[index] = cx + (xs[index] - cx) * 0.94 / radius
                    ys[index] = cy + (ys[index] - cy) * 0.94 / radius
        positions.update({node_id: [round(x, 6), round(y, 6)] for node_id, x, y in zip(members, xs, ys, strict=True)})
    return positions, regions


def build_production_figure(model, positions, layout_regions=None, *, title, direction_key, legend_title):
    """Return a figure without mutating the prepared model or layout inputs."""
    nodes, edges = model["nodes"], model["edges"]
    node_ids = [node["id"] for node in nodes]
    node_by_id = model["node_by_id"]
    background_x, background_y = [], []
    for edge in edges:
        source, target = positions[edge["source"]], positions[edge["target"]]
        background_x.extend([source[0], target[0], None])
        background_y.extend([source[1], target[1], None])
    permanent_annotations = [
        {
            "x": positions[node["id"]][0],
            "y": positions[node["id"]][1],
            "xref": "x",
            "yref": "y",
            "text": node["name"],
            "showarrow": False,
            "xanchor": "right" if node["role"] == "mineral" else "left",
            "xshift": -9 if node["role"] == "mineral" else 9,
            "font": {"size": 11, "color": "#222"},
        }
        for node in nodes
        if node["role"] in {"mineral", "external_group"}
    ]
    cloud_names = {
        "mineral": "Mineral<br>inputs",
        "external_input": "External<br>inputs",
        "panel": "Study panel",
        "external_group": "External output<br>groups",
    }
    for role, text in cloud_names.items():
        members = [positions[node["id"]] for node in nodes if node["role"] == role]
        if not members:
            continue
        if layout_regions is not None:
            x0, x1, y0, y1 = layout_regions[role]
        else:
            x0, x1 = min(point[0] for point in members), max(point[0] for point in members)
            y0, y1 = min(point[1] for point in members), max(point[1] for point in members)
        if role == "panel":
            x, y, anchor = x1 - 1.5, y1 + 0.45, "left"
        elif role == "external_group":
            x, y, anchor = x1 + 0.9, (y0 + y1) / 2, "left"
        else:
            x, y, anchor = x0 - (0.95 if role == "mineral" else 0.5), (y0 + y1) / 2, "right"
        permanent_annotations.append(
            {
                "name": f"cloud:{role}",
                "x": x,
                "y": y,
                "xref": "x",
                "yref": "y",
                "text": f"<b>{text}</b>",
                "showarrow": False,
                "xanchor": anchor,
                "align": anchor,
                "font": {"size": 12, "color": "#626972"},
            }
        )
    permanent_annotations.append(
        {
            "name": "direction-key",
            "xref": "paper",
            "yref": "paper",
            "x": 0,
            "y": 1.04,
            "text": direction_key,
            "showarrow": False,
            "xanchor": "left",
            "font": {"size": 11, "color": "#626972"},
        }
    )
    figure = go.Figure()
    # Keep the edge trace first so the interactive node trace has a stable explicit index.
    figure.add_trace(
        go.Scatter(
            x=background_x,
            y=background_y,
            mode="lines",
            line={"color": "rgba(120,120,120,0.12)", "width": 0.7},
            hoverinfo="skip",
            showlegend=False,
            name="Production links",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[positions[node_id][0] for node_id in node_ids],
            y=[positions[node_id][1] for node_id in node_ids],
            mode="markers",
            marker={
                "size": [14 if node_by_id[node_id]["role"] in {"mineral", "panel"} else 9 for node_id in node_ids],
                "opacity": 1,
                "color": [node_by_id[node_id]["color"] for node_id in node_ids],
                "line": {"width": 0.5, "color": "#555"},
            },
            customdata=[{"id": node_id} for node_id in node_ids],
            hoverinfo="none",
            showlegend=False,
            name="Production nodes",
        )
    )
    for category in sorted(model["category_colors"]):
        figure.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker={"size": 9, "color": model["category_colors"][category]},
                name=category,
                meta={"category": category},
                hoverinfo="skip",
            )
        )
    figure.update_layout(
        title=title,
        height=780,
        margin={"l": 85, "r": 110, "t": 60, "b": 175, "autoexpand": False},
        xaxis={"visible": False, "range": [-7.0, 7.0], "fixedrange": False},
        yaxis={"visible": False, "range": [-4.8, 4.8], "fixedrange": False},
        dragmode="pan",
        hovermode="closest",
        annotations=permanent_annotations,
        legend={"title": {"text": legend_title, "side": "top"}, "orientation": "h", "y": -0.06},
        plot_bgcolor="white",
    )
    return figure


def build_production_graph(
    links,
    panel_items,
    reference_types,
    meta_groups,
    mineral_ids,
    category_palette,
    layout_seed=17,
    *,
    title="Study-panel manufacturing relationships",
    direction_key="Material → product",
    legend_title="Item category",
):
    """Prepare, lay out, and render the compatible in-memory production graph."""
    model = prepare_production_graph(links, panel_items, reference_types, meta_groups, mineral_ids, category_palette)
    positions, regions = layout_production_graph(model, layout_seed)
    figure = build_production_figure(
        model,
        positions,
        regions,
        title=title,
        direction_key=direction_key,
        legend_title=legend_title,
    )
    permanent_annotations = [annotation.to_plotly_json() for annotation in figure.layout.annotations]
    model.update({"positions": positions, "layout_regions": regions, "permanent_annotations": permanent_annotations})
    return figure, model


def production_graph_browser_model(model):
    """Return only browser interaction records, not preparation-only source dictionaries."""
    return {
        "nodes": [{key: node[key] for key in ("id", "name", "role", "category")} for node in model["nodes"]],
        "edges": [
            {key: edge[key] for key in ("source", "target", "kind") if key in edge}
            | ({"product_label": edge["product_label"]} if "product_label" in edge else {})
            for edge in model["edges"]
        ],
        "positions": model["positions"],
        "incident_edges": model["incident_edges"],
        "permanent_annotations": model["permanent_annotations"],
        "baseline": {"panel_size": 14, "external_size": 9, "outline_width": 0.5},
    }


def production_graph_html(figure, model):
    """Embed Plotly and the packaged interaction script in an HTML graph fragment."""
    browser_model = production_graph_browser_model(
        {
            **model,
            "permanent_annotations": [annotation.to_plotly_json() for annotation in figure.layout.annotations],
        }
    )
    post_script = _interaction_script(browser_model)
    return pio.to_html(
        figure,
        full_html=False,
        include_plotlyjs=True,
        post_script=post_script,
        config={"doubleClick": False, "responsive": True},
    )
