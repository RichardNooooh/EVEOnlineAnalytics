const graph = document.getElementById("{plot_id}");
const model = __PRODUCTION_GRAPH_MODEL__;
const nodeCurve = 1;
let hovered = null;
let pinned = null;
let focusedCategory = null;
let desiredActive = null;
let renderedActive = Symbol("unrendered");
let renderQueued = false;
let selectionTime = -Infinity;
let renderFailed = false;
let pointer = null;
// Plotly's point event and the bubbling click belong to one gesture, not one event object.
let pointClicked = false;
const byId = Object.fromEntries(model.nodes.map(node => [node.id, node]));
function activeNode() { return pinned || hovered; }
function nodeSize(node, activeId) {
  return node.id === activeId ? 16 : (["mineral", "panel"].includes(node.role) ? model.baseline.panel_size : model.baseline.external_size);
}
function outlineWidth(node, activeId, related, category = null) {
  if (activeId) return node.id === activeId ? 2.8 : (related.has(node.id) ? 2 : model.baseline.outline_width);
  return node.role === "panel" && node.category === category ? 2.4 : model.baseline.outline_width;
}
function activeAnnotations(activeId) {
  const annotations = model.permanent_annotations.slice();
  const related = new Set();
  if (!activeId) return {annotations, related};
  const node = byId[activeId];
  related.add(activeId);
  for (const index of model.incident_edges[activeId]) {
    const edge = model.edges[index];
    const otherId = edge.source === activeId ? edge.target : edge.source;
    related.add(otherId);
    const source = model.positions[edge.source], target = model.positions[edge.target];
    annotations.push({
      x: target[0], y: target[1], ax: source[0], ay: source[1], xref: "x", yref: "y", axref: "x", ayref: "y",
      showarrow: true, arrowhead: 2, arrowsize: 0.7, arrowwidth: 1.5, arrowcolor: "rgba(45,45,45,0.85)",
      standoff: nodeSize(byId[edge.target], activeId) / 2 + outlineWidth(byId[edge.target], activeId, related) / 2,
      text: "", font: {color: "rgba(0,0,0,0)"},
    });
    if (node.role === "panel" && edge.target === activeId && byId[edge.source].role === "external_input") {
      const input = byId[edge.source];
      annotations.push({x: model.positions[input.id][0], y: model.positions[input.id][1], xref: "x", yref: "y", text: input.name, showarrow: false, xshift: -8, xanchor: "right", font: {size: 10, color: "#333"}, bgcolor: "rgba(255,255,255,0.88)"});
    }
    if (node.role === "panel" && edge.source === activeId && edge.kind === "aggregate") {
      annotations.push({x: (source[0] + target[0]) / 2, y: (source[1] + target[1]) / 2, xref: "x", yref: "y", text: edge.product_label, showarrow: false, font: {size: 10, color: "#333"}, bgcolor: "rgba(255,255,255,0.9)"});
    }
  }
  if (node.role === "panel" || node.role === "external_input") annotations.push({x: model.positions[activeId][0], y: model.positions[activeId][1], xref: "x", yref: "y", text: node.name, showarrow: false, yshift: 15, font: {size: 12, color: "#111"}, bgcolor: "rgba(255,255,255,0.88)"});
  return {annotations, related};
}
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  Promise.resolve().then(async () => {
    let attemptedActive = null;
    try {
      while (renderedActive !== desiredActive) {
        const state = desiredActive;
        const [activeId, category] = JSON.parse(state);
        attemptedActive = state;
        const detail = activeAnnotations(activeId);
        const related = detail.related;
        await Promise.resolve(Plotly.update(graph, {
          "marker.opacity": [model.nodes.map(() => 1)],
          "marker.size": [model.nodes.map(node => nodeSize(node, activeId))],
          "marker.line.width": [model.nodes.map(node => outlineWidth(node, activeId, related, category))],
          "marker.line.color": [model.nodes.map(node => activeId ? (related.has(node.id) ? "#202832" : "#555") : (node.role === "panel" && node.category === category ? "#202832" : "#555"))],
        }, {annotations: detail.annotations}, [nodeCurve]));
        renderedActive = state;
      }
    } catch (error) {
      if (desiredActive === attemptedActive) {
        renderedActive = attemptedActive;
        renderFailed = true;
        console.error("Production graph interaction update failed", error);
      }
    } finally {
      renderQueued = false;
      if (renderedActive !== desiredActive) queueRender();
    }
  });
}
function requestRender() {
  // Category changes underneath an inspection do not change its rendered view.
  desiredActive = JSON.stringify([activeNode(), activeNode() ? null : focusedCategory]);
  if (renderFailed || desiredActive !== renderedActive) {
    renderFailed = false;
    queueRender();
  }
}
function clear() { pinned = null; hovered = null; requestRender(); }
function pointEvent(event) { return event && event.event; }
function pointAtPointer(point, event) {
  const nativeEvent = pointEvent(event);
  const marker = graph.querySelectorAll(".scatterlayer .trace")[nodeCurve]?.querySelectorAll(".point")[point.pointNumber];
  if (!nativeEvent || !marker) return false;
  const bounds = marker.getBoundingClientRect();
  const distance = Math.hypot(nativeEvent.clientX - bounds.x - bounds.width / 2, nativeEvent.clientY - bounds.y - bounds.height / 2);
  // Plotly can click its cached hover point after a rapid move into blank space.
  return distance <= Math.max(bounds.width, bounds.height) / 2 + (graph.layout.hoverdistance ?? 20);
}
function protectedTarget(target) { return target && target.closest(".modebar, .legend, .annotation, .infolayer, .xaxislayer-above, .yaxislayer-above, .rangeslider-container, .rangeselector"); }
graph.on("plotly_hover", event => {
  const point = event.points && event.points[0];
  const nativeEvent = pointEvent(event);
  // A redraw can replay an older mouse event; it must not undo a later click.
  if (!nativeEvent || nativeEvent.timeStamp <= selectionTime) return;
  if (!pinned && point && point.curveNumber === nodeCurve) { hovered = point.customdata.id; requestRender(); }
});
graph.on("plotly_unhover", event => {
  const nativeEvent = pointEvent(event);
  if (!nativeEvent || nativeEvent.timeStamp <= selectionTime) return;
  if (!pinned && hovered !== null) { hovered = null; requestRender(); }
});
graph.on("plotly_click", event => {
  const point = event.points && event.points[0];
  if (!point || point.curveNumber !== nodeCurve || !pointAtPointer(point, event)) return;
  selectionTime = pointEvent(event)?.timeStamp ?? selectionTime;
  pointClicked = true;
  const id = point.customdata.id;
  if (pinned === id) clear(); else { pinned = id; hovered = null; requestRender(); }
});
graph.on("plotly_legendclick", event => {
  const category = event.data[event.curveNumber].meta?.category;
  if (!category) return false;
  selectionTime = pointEvent(event)?.timeStamp ?? selectionTime;
  pinned = null; hovered = null;
  focusedCategory = focusedCategory === category ? null : category;
  requestRender();
  return false; // Categories select; Plotly must never hide or isolate traces.
});
graph.on("plotly_legenddoubleclick", () => false);
graph.addEventListener("pointerdown", event => { pointClicked = false; pointer = {x: event.clientX, y: event.clientY, moved: false}; });
graph.addEventListener("pointermove", event => { if (pointer && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 4) pointer.moved = true; });
graph.addEventListener("pointerup", () => { /* preserve movement state until click */ });
graph.addEventListener("click", event => {
  const moved = pointer && pointer.moved;
  const clickedNode = pointClicked;
  pointClicked = false;
  pointer = null;
  if (clickedNode || moved || protectedTarget(event.target)) return;
  if (event.target && event.target.closest(".nsewdrag")) { selectionTime = event.timeStamp ?? selectionTime; focusedCategory = null; clear(); }
});
requestRender();
