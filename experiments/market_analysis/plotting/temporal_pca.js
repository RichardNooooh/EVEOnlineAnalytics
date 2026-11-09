(function () {
  const graph = document.getElementById('{plot_id}');
  const model = __TEMPORAL_PCA_MODEL__;
  const base = Date.parse(model.first_date + 'T00:00:00Z');
  const date = day => new Date(base + day * 86400000).toISOString().slice(0, 10);
  const day = value => Math.round((Date.parse(value + 'T00:00:00Z') - base) / 86400000);
  const controls = document.createElement('div');
  controls.className = 'temporal-pca-controls';
  controls.setAttribute('aria-busy', 'true');
  controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:12px;align-items:end;font:14px sans-serif;margin:8px 0';
  controls.innerHTML = '<label>Scope <select data-control="scope"><option value="item">Selected item</option><option value="all">All items</option></select></label>' +
    '<label>Item <select data-control="item"></select></label>' +
    '<label>Start <input data-control="start" type="date"></label>' +
    '<label>End <input data-control="end" type="date"></label>' +
    '<label><input data-control="trajectory" type="checkbox"> Trajectory</label>' +
    '<label>Range <select data-control="range"><option value="full">Full</option><option value="central">Central</option></select></label>' +
    '<span data-control="status" role="status"></span>';
  graph.parentNode.insertBefore(controls, graph);
  const get = name => controls.querySelector('[data-control="' + name + '"]');
  const item = get('item'), start = get('start'), end = get('end'), trajectory = get('trajectory');
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  model.items.forEach((group, index) => {
    const option = document.createElement('option');
    option.value = index;
    option.textContent = group.name + ' (' + group.id + ')';
    item.appendChild(option);
    const prefix = escape(group.name) + ' (' + group.id + ')<br>';
    group.hover = group.rows.map(row => prefix + model.date_labels[row]);
  });
  start.min = end.min = start.value = date(0);
  start.max = end.max = end.value = date(model.last_day);
  const context = graph.data[0];
  const axes = [context.x, context.y, context.z];
  const lower = (array, value) => {
    let lo = 0, hi = array.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (array[mid] < value) lo = mid + 1; else hi = mid; }
    return lo;
  };
  function state() {
    const scope = get('scope').value;
    item.disabled = trajectory.disabled = scope === 'all';
    return {scope, item: scope === 'item' ? Number(item.value) : null,
      start: start.value, end: end.value, trajectory: scope === 'item' && trajectory.checked,
      range: get('range').value};
  }
  function selectionKey(s) { return JSON.stringify([s.scope, s.item, s.start, s.end, s.trajectory]); }
  function select(s) {
    const a = day(s.start), b = day(s.end);
    const valid = Number.isFinite(a) && Number.isFinite(b) && a <= b;
    const groups = s.scope === 'all' ? model.items : [model.items[s.item]];
    const rows = [], colors = [], text = [], line = [[], [], []];
    let clipped = 0, count = 0;
    for (const group of groups) {
      if (!group || !valid) continue;
      const lo = lower(group.days, a), hi = lower(group.days, b + 1);
      if (hi > lo) count++;
      clipped += group.clipped_prefix[hi] - group.clipped_prefix[lo];
      for (const row of group.rows.slice(lo, hi)) rows.push(row);
      for (const value of group.days.slice(lo, hi)) colors.push(value);
      for (const label of group.hover.slice(lo, hi)) text.push(label);
      if (s.trajectory) {
        for (let i = lo; i < hi; i++) {
          if (i > lo && !group.adjacent[i]) line.forEach(axis => axis.push(null));
          axes.forEach((axis, j) => line[j].push(axis[group.rows[i]]));
        }
      }
    }
    const coords = axes.map(axis => rows.map(row => axis[row]));
    const one = valid && a === b;
    const tickvals = valid ? (one ? [a] : [a, b]) : [];
    const endpoint = index => s.scope === 'item' && rows.length ? coords.map(axis => [axis[index]]) : [[], [], []];
    const first = endpoint(0), last = endpoint(rows.length - 1);
    const endpointText = index => s.scope === 'item' && rows.length ? [text[index]] : [];
    return {clipped, count, size: rows.length, update: {
      x: [coords[0], line[0], first[0], last[0]], y: [coords[1], line[1], first[1], last[1]],
      z: [coords[2], line[2], first[2], last[2]],
      text: [text, [], endpointText(0), endpointText(rows.length - 1)],
      'marker.color': [colors, undefined, undefined, undefined],
      'marker.cmin': [valid ? (one ? a - 0.5 : a) : 0, undefined, undefined, undefined],
      'marker.cmax': [valid ? (one ? b + 0.5 : b) : 1, undefined, undefined, undefined],
      'marker.colorbar.tickvals': [tickvals, undefined, undefined, undefined],
      'marker.colorbar.ticktext': [tickvals.map(date), undefined, undefined, undefined],
      'marker.showscale': [rows.length > 0, undefined, undefined, undefined]
    }};
  }
  let pending = false, dirty = false, committed = null, cached = null;
  async function draw() {
    const next = state(), key = selectionKey(next);
    const selectionChanged = !committed || key !== committed.key;
    const rangeChanged = !committed || next.range !== committed.range;
    if (!selectionChanged && !rangeChanged) return;
    const selection = selectionChanged ? select(next) : cached;
    const layout = {};
    if (rangeChanged) {
      const ranges = next.range === 'full' ? model.full_ranges : model.central_ranges;
      Object.assign(layout, {'scene.xaxis.range': ranges[0], 'scene.yaxis.range': ranges[1], 'scene.zaxis.range': ranges[2]});
    }
    await Plotly.update(graph, selectionChanged ? selection.update : {}, layout, selectionChanged ? [1, 2, 3, 4] : []);
    cached = selection;
    committed = {key, range: next.range};
    get('status').textContent = selection.size ? `${selection.size} observations · ${selection.count} items · ${next.range === 'central' ? selection.clipped : 0} clipped` : 'No observations in selected interval';
  }
  async function schedule() {
    dirty = true;
    controls.setAttribute('aria-busy', 'true');
    if (pending) return;
    pending = true;
    try {
      while (dirty) {
        dirty = false;
        try { await draw(); }
        catch (error) { get('status').textContent = 'Unable to render selection: ' + error.message; }
      }
    } finally {
      pending = false;
      controls.setAttribute('aria-busy', 'false');
    }
  }
  controls.addEventListener('change', schedule);
  schedule();
}());
