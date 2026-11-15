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
    (model.study_categories ? '<label>Category <select data-control="category"><option value="">All categories</option></select></label>' +
      '<label>Color by <select data-control="color"><option value="date">Date</option><option value="category">Study category</option></select></label>' : '') +
    '<label>Start <input data-control="start" type="date"></label>' +
    '<label>End <input data-control="end" type="date"></label>' +
    '<label><input data-control="trajectory" type="checkbox"> Trajectory</label>' +
    '<label>Range <select data-control="range"><option value="full">Full</option><option value="central">Central</option></select></label>' +
    '<span data-control="status" role="status"></span><span data-control="key"></span>';
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
    group.hover = group.rows.map(row => prefix + (model.week_starts ? model.week_starts[row] + ' – ' : '') + model.date_labels[row] +
      (model.study_categories ? '<br>Category: ' + escape(model.study_categories[row]) : ''));
  });
  if (model.study_categories) {
    [...new Set(model.study_categories)].sort().forEach(category => {
      const option = document.createElement('option');
      option.value = option.textContent = category;
      get('category').appendChild(option);
    });
  }
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
      range: get('range').value, category: model.study_categories ? get('category').value : '',
      color: model.study_categories ? get('color').value : 'date'};
  }
  function selectionKey(s) { return JSON.stringify([s.scope, s.item, s.start, s.end, s.trajectory, s.category, s.color]); }
  function select(s) {
    const a = day(s.start), b = day(s.end);
    const valid = Number.isFinite(a) && Number.isFinite(b) && a <= b;
    const groups = s.scope === 'all' ? model.items : [model.items[s.item]];
    const rows = [], colors = [], text = [], line = [[], [], []];
    let clipped = 0, count = 0;
    for (const group of groups) {
      if (!group || !valid) continue;
      const lo = lower(group.days, a), hi = lower(group.days, b + 1);
      let included = false, previous = -1;
      for (let i = lo; i < hi; i++) {
        const row = group.rows[i];
        if (s.category && model.study_categories[row] !== s.category) continue;
        included = true;
        clipped += group.clipped_prefix[i + 1] - group.clipped_prefix[i];
        rows.push(row);
        colors.push(s.color === 'category' ? model.category_colors[model.study_categories[row]] : group.days[i]);
        text.push(group.hover[i]);
        if (s.trajectory) {
          if (previous !== -1 && (previous !== i - 1 || !group.adjacent[i])) line.forEach(axis => axis.push(null));
          axes.forEach((axis, j) => line[j].push(axis[group.rows[i]]));
          previous = i;
        }
      }
      if (included) count++;
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
      'marker.showscale': [s.color === 'date' && rows.length > 0, undefined, undefined, undefined]
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
    const keyElement = get('key');
    keyElement.replaceChildren();
    if (next.color === 'category') {
      [...new Set(model.study_categories)].sort().filter(c => !next.category || c === next.category).forEach(category => {
        const label = document.createElement('span'), swatch = document.createElement('span');
        swatch.style.cssText = 'display:inline-block;width:10px;height:10px;margin:0 4px 0 10px';
        swatch.style.backgroundColor = model.category_colors[category];
        label.append(swatch, document.createTextNode(category));
        keyElement.appendChild(label);
      });
    }
    get('status').textContent = selection.size ? `${selection.size} observations · ${selection.count} items · ${next.range === 'central' ? selection.clipped : 0} clipped${model.week_starts ? ' · week ends ' + next.start + ' – ' + next.end : ''}` : 'No observations in selected interval';
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
