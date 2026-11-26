/*
 * Browser-only anywidget renderer for 02b.
 *
 * Python traits (both sync=True):
 *   payload: Dict
 *   view_state: Dict, initially {} and thereafter {date: string, focus_id: string|null}
 * _esm = pathlib.Path("experiments/market_analysis/peer_network.mjs")
 *
 * payload = {
 *   entry: 0.70,
 *   nodes: [{id: "34", name: "Tritanium", category: "Minerals"}, ...],
 *   weeks: [{
 *     date: "2026-06-07",                         // increasing ISO dates
 *     positions: [[x, y], ...],                    // one per node, common fixed frame
 *     edges: [{source: "34", target: "35", wins: 18, usable: 26, age: 8}, ...]
 *   }, ...]
 * }
 * A week without a computed snapshot uses positions: null, edges: null.
 * Edges are sparse, unordered, unique active pairs; scores are wins / usable.
 * Positions are finite and normalized to [-1,1] in both axes, including across
 * payload changes. Include all relevant weeks, including no-snapshot weeks.
 * The first computed snapshot is initial inventory (zero additions/removals).
 * Later counts compare the preceding computed chronological snapshot.
 *
 * On payload replacement, the widget keeps the selected date and focus ID if
 * available; otherwise it chooses the closest earlier date (or the first date)
 * and clears a missing focus. view_state survives remount/reconnect when the
 * same widget model is reused. Playback sends state only at weekly landings,
 * never for animation frames. The parent may compose rule controls separately.
 */

// Fixed keys keep colors stable when categories are absent from a payload.
const categoryColors = {
  "Battleships": ["#005a9c", "#70bfff"],
  "Cruisers and battlecruisers": ["#7836a0", "#d3a4fa"],
  "Freighters": ["#006b63", "#66d7c8"],
  "Light ships": ["#a22c68", "#ff9ac6"],
  "Mining and industrial ships": ["#605500", "#e5d067"],
  "Defense and repair": ["#ad3900", "#ffad79"],
  "Exploration and resource recovery": ["#295b22", "#a1d789"],
  "Miscellaneous modules": ["#943b38", "#ffaaa4"],
  "Mobility and concealment": ["#3c4da5", "#aebaff"],
  "Ammunition and probes": ["#00677f", "#7bd8ed"],
  "Deployables": ["#a32225", "#ff999b"],
  "Drones": ["#7e3890", "#e8a4ee"],
  "Minerals": ["#505c68", "#bac8d6"],
  "Rigs": ["#795000", "#eac180"],
};
const categoryName = node => typeof node?.category === "string" && node.category.trim() || "Uncategorized";
const categoryColor = (category, dark) => (categoryColors[category] || ["#505c68", "#bac8d6"])[dark ? 1 : 0];

const css = `
.pn{--bg:#fff;--fg:#1c293c;--muted:#53647a;--border:#c7d0dd;--control:#f4f7fb;--grid:#d5dce5;--add:#08734e;--remove:#b33932;color:var(--fg);background:var(--bg);font:14px/1.4 system-ui,sans-serif;border:1px solid var(--border);border-radius:10px;padding:12px}
@media(prefers-color-scheme:dark){.pn{--bg:#151d29;--fg:#ecf1f8;--muted:#bac7d8;--border:#465569;--control:#243245;--grid:#455469;--add:#6fe0ac;--remove:#ff9790}}
.pn *{box-sizing:border-box}.pn{min-width:0}.pn-head{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.pn-summary{font-weight:650;flex:1;min-width:0}.pn-search{display:flex;gap:6px;align-items:center;min-width:0}.pn input,.pn button{font:inherit;color:var(--fg);background:var(--control);border:1px solid var(--border);border-radius:5px;padding:5px 8px}.pn input{width:min(270px,45vw)}.pn button{cursor:pointer}.pn button:focus-visible,.pn input:focus-visible,.pn summary:focus-visible,.pn-timeline:focus-visible,.pn-graph:focus-visible{outline:3px solid #339fea;outline-offset:2px}
.pn-legend{margin:6px 0}.pn-legend summary{cursor:pointer;width:fit-content}.pn-legend-list{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}.pn-legend-list button{display:inline-flex;align-items:center;gap:5px;font-size:12px;text-align:left;max-width:100%}.pn-legend-list button[aria-pressed=true]{outline:2px solid var(--fg);outline-offset:-2px}.pn-check{width:1em}.pn-swatch{display:inline-block;width:10px;height:10px;flex:none;border-radius:50%;background:var(--swatch);border:1px solid var(--fg)}.pn-category{display:flex;align-items:center;gap:4px;color:var(--muted);font-size:11px}
@media(max-width:500px){.pn-summary{flex-basis:100%}}
.pn-body{container-type:inline-size}.pn-panels{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;align-items:start}@container (min-width: 1050px){.pn-panels{grid-template-columns:minmax(0,1fr) minmax(440px,40%)}}.pn-graph-window{min-width:0}.pn-graph{display:block;touch-action:none;cursor:grab}.pn-graph:active{cursor:grabbing}.pn-camera{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.pn-key{color:var(--muted);font-size:12px}.pn-controls{display:flex;align-items:center;gap:10px}.pn-timeline{flex:1;width:100%;height:70px;min-width:0;cursor:crosshair;touch-action:none}.pn-changes{margin-top:6px;font-size:13px}.pn-changes .gained{color:var(--add)}.pn-changes .lost{color:var(--remove)}.pn-neighbors{color:var(--muted);min-width:0;overflow-x:auto}.pn-neighbors strong{color:var(--fg)}.pn-neighbors table{border-collapse:collapse;width:100%;font-size:12px;color:var(--fg)}.pn-neighbors th,.pn-neighbors td{padding:2px 9px 2px 0;text-align:left;border-bottom:1px solid var(--border)}.pn-neighbors tbody tr{cursor:default}.pn-neighbors tbody tr:hover,.pn-neighbors tbody tr:focus-visible{background:var(--control);color:var(--fg);outline:2px solid #339fea;outline-offset:-2px}.pn-empty{padding:5px 0}
`;

function render({ model, el }) {
  el.innerHTML = `<style>${css}</style><section class="pn" aria-label="Weekly item peer network">
    <div class="pn-head"><div class="pn-summary" aria-live="polite"></div>
      <div class="pn-search"><label>Focus item <input list="pn-items" placeholder="Search item" aria-label="Search item"></label><datalist id="pn-items"></datalist><button class="pn-clear" type="button">Clear</button></div></div>
    <div class="pn-body"><div class="pn-panels"><div><div class="pn-camera"><button class="pn-zoom-out" type="button" aria-label="Zoom out">−</button><button class="pn-zoom-in" type="button" aria-label="Zoom in">+</button><button class="pn-fit" type="button">Fit network</button><span class="pn-key">Drag to pan · pinch or Ctrl/⌘-wheel to zoom · arrows pan graph</span></div><div class="pn-graph-window"><canvas class="pn-graph" tabindex="0" aria-label="Network graph. Click a node to focus it; drag or use arrow keys to pan."></canvas></div>
    <div class="pn-key">Agreement: orange → purple · opacity: fresh-week age · <span style="color:var(--add)">solid green: arriving</span> · <span style="color:var(--remove)">dashed red: departing</span> · positions aid tracking, not measured clusters</div>
    <details class="pn-legend"><summary>Categories · highlight</summary><div class="pn-legend-list" aria-label="Highlight a category"></div></details>
    <div class="pn-controls"><button class="pn-play" type="button">Play</button><canvas class="pn-timeline" tabindex="0" role="slider" aria-label="Week timeline" aria-valuemin="0"></canvas></div>
    <div class="pn-key">Timeline: additions above, removals below · click or drag to seek · arrow keys step, Home/End jump</div>
    <div class="pn-changes" aria-live="polite"></div></div><div class="pn-neighbors"></div></div></div>
  </section>`;
  const root = el.querySelector(".pn");
  const graph = root.querySelector(".pn-graph"), timeline = root.querySelector(".pn-timeline");
  const graphWindow = root.querySelector(".pn-graph-window");
  const summary = root.querySelector(".pn-summary"), search = root.querySelector("input");
  const list = root.querySelector("datalist"), neighbors = root.querySelector(".pn-neighbors");
  const changes = root.querySelector(".pn-changes");
  const legend = root.querySelector(".pn-legend-list");
  const play = root.querySelector(".pn-play"), clear = root.querySelector(".pn-clear");
  const zoomIn = root.querySelector(".pn-zoom-in"), zoomOut = root.querySelector(".pn-zoom-out"), fit = root.querySelector(".pn-fit");
  // Datalist IDs are document-scoped: separate widget instances must not collide.
  const listId = `pn-items-${Math.random().toString(36).slice(2)}`;
  list.id = listId; search.setAttribute("list", listId);
  let data, nodes, indexById, snapshots, counts, week = 0, focus = null;
  let playing = false, animation = null, raf = 0, timer = 0, disposed = false;
  let hoveredPeer = null, focusedPeer = null;
  let neighborFocus = null;
  let highlightedCategory = null;
  let displayedPositions = [];
  let anchorFocus = null;
  const labelAnchors = new Map();
  const camera = {scale:1,x:0,y:0};
  const pointers = new Map();
  let gesture = null, suppressClick = false;
  let saveTimer = 0;
  const pairKey = (a, b) => a < b ? JSON.stringify([a, b]) : JSON.stringify([b, a]);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const state = () => ({ date: data?.weeks[week]?.date ?? null, focus_id: focus });

  function save() {
    clearTimeout(saveTimer);
    // Keep local remount state current without a kernel round trip per drag event.
    model.set("view_state", state());
    saveTimer = setTimeout(() => { saveTimer = 0; if (!disposed) model.save_changes(); }, 100);
  }
  function stop() {
    playing = false; animation = null; cancelAnimationFrame(raf); clearTimeout(timer);
    play.textContent = "Play"; play.setAttribute("aria-label", "Play");
  }
  function setup(payload, restored) {
    if (!payload || !Array.isArray(payload.weeks) || !Array.isArray(payload.nodes)) return;
    const previous = data ? state() : (restored || {});
    stop(); data = payload;
    nodes = data.nodes; indexById = new Map(nodes.map((n, i) => [String(n.id), i]));
    snapshots = data.weeks.map(w => {
      if (!Array.isArray(w.edges) || !Array.isArray(w.positions)) return null;
      return new Map(w.edges.map(e => [pairKey(String(e.source), String(e.target)), e]));
    });
    let last = null;
    counts = snapshots.map(s => {
      if (!s) return null;
      const result = {active:s.size, added:0, removed:0};
      if (last) {
        for (const key of s.keys()) if (!last.has(key)) result.added++;
        for (const key of last.keys()) if (!s.has(key)) result.removed++;
      }
      last = s; return result;
    });
    week = data.weeks.findIndex(w => w.date === previous.date);
    if (week < 0) {
      week = previous.date ? data.weeks.findLastIndex(w => w.date <= previous.date) : data.weeks.length - 1;
      if (week < 0) week = 0;
    }
    focus = previous.focus_id != null && indexById.has(String(previous.focus_id)) ? String(previous.focus_id) : null;
    list.replaceChildren(...nodes.map(n => {
      const opt = document.createElement("option"); opt.value = `${n.name} (${n.id})`; return opt;
    }));
    const categories = [...new Set(nodes.map(categoryName))].sort((a,b) => a.localeCompare(b));
    if (!categories.includes(highlightedCategory)) highlightedCategory = null;
    legend.replaceChildren(...categories.map(category => {
      const button = document.createElement("button");
      button.type = "button"; button.dataset.category = category;
      const check = document.createElement("span"); check.className = "pn-check"; check.setAttribute("aria-hidden", "true");
      const swatch = document.createElement("span"); swatch.className = "pn-swatch"; swatch.setAttribute("aria-hidden", "true");
      button.append(check, swatch, document.createTextNode(category));
      button.addEventListener("click", () => {
        highlightedCategory = highlightedCategory === category ? null : category;
        updateLegend(); draw();
      });
      return button;
    }));
    updateLegend(); syncSearch(); update(); save();
  }
  function updateLegend() {
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    legend.querySelectorAll("button").forEach(button => {
      const selected = button.dataset.category === highlightedCategory;
      button.setAttribute("aria-pressed", String(selected));
      button.querySelector(".pn-check").textContent = selected ? "✓" : "";
      button.querySelector(".pn-swatch").style.setProperty("--swatch", categoryColor(button.dataset.category, dark));
    });
    neighbors.querySelectorAll(".pn-category").forEach(element => {
      element.querySelector(".pn-swatch").style.setProperty("--swatch", categoryColor(element.dataset.category, dark));
    });
  }
  function syncSearch() {
    const n = focus == null ? null : nodes[indexById.get(focus)];
    search.value = n ? `${n.name} (${n.id})` : "";
  }
  function previousSnapshot(i) {
    for (let j = i - 1; j >= 0; j--) if (snapshots[j]) return j;
    return -1;
  }
  function edgeNodes(e) {
    return [indexById.get(String(e.source)), indexById.get(String(e.target))];
  }
  function update() {
    if (!data || !data.weeks.length) {
      summary.textContent = "No weeks available"; timeline.setAttribute("aria-valuemax", "0"); return;
    }
    const w = data.weeks[week], c = counts[week];
    const peerCount = focus && snapshots[week] ? [...snapshots[week].values()].filter(e => String(e.source) === focus || String(e.target) === focus).length : null;
    summary.textContent = c ? `${w.date} · ${c.active} active · +${c.added} / −${c.removed} · network-wide${focus ? ` · ${peerCount} active peers` : ""}` : `${w.date} · No snapshot${focus ? " · focus selected" : ""}`;
    timeline.setAttribute("aria-valuemax", String(data.weeks.length - 1));
    timeline.setAttribute("aria-valuenow", String(week));
    timeline.setAttribute("aria-valuetext", summary.textContent);
    updateChanges(); updateNeighbors(); draw();
  }
  function focusedChanges(i) {
    const current = snapshots[i], prior = previousSnapshot(i);
    if (!focus || !current) return null;
    if (prior < 0) return {inventory: true, gained: [], lost: []};
    const previous = snapshots[prior];
    const other = e => String(e.source) === focus ? String(e.target) : String(e.source);
    const incident = e => String(e.source) === focus || String(e.target) === focus;
    return {
      inventory: false,
      gained: [...current].filter(([key, e]) => incident(e) && !previous.has(key)).map(([, e]) => other(e)),
      lost: [...previous].filter(([key, e]) => incident(e) && !current.has(key)).map(([, e]) => other(e))
    };
  }
  function updateChanges() {
    changes.replaceChildren();
    if (!focus) return;
    const n = nodes[indexById.get(focus)], delta = focusedChanges(week);
    if (!delta) { changes.textContent = `${n.name}: no snapshot`; return; }
    if (delta.inventory) { changes.textContent = `${n.name}: initial inventory · no gained or lost neighbors`; return; }
    const names = ids => ids.map(id => nodes[indexById.get(id)]?.name ?? id).sort((a,b) => a.localeCompare(b)).join(", ") || "none";
    const lead = document.createElement("strong"); lead.textContent = `${n.name} · this week: `;
    const gained = document.createElement("span"); gained.className = "gained"; gained.textContent = `Gained: ${names(delta.gained)}`;
    const lost = document.createElement("span"); lost.className = "lost"; lost.textContent = `Lost: ${names(delta.lost)}`;
    changes.append(lead, gained, document.createTextNode(" · "), lost);
  }
  function updateNeighbors() {
    const hadFocus = neighbors.contains(document.activeElement);
    const restorePeer = hadFocus && neighborFocus === focus ? focusedPeer : null;
    neighbors.replaceChildren();
    if (neighborFocus !== focus) hoveredPeer = focusedPeer = null;
    else if (restorePeer) focusedPeer = restorePeer;
    neighborFocus = focus;
    if (!focus) { neighbors.textContent = "Select an item to inspect its active neighbors."; return; }
    const name = nodes[indexById.get(focus)].name, edges = snapshots[week];
    const title = document.createElement("strong");
    title.textContent = `${name} · ${edges ? "active neighbors" : "no snapshot"}`;
    neighbors.append(title);
    if (!edges) return;
    const rows = [...edges.values()].filter(e => String(e.source) === focus || String(e.target) === focus)
      .sort((a,b) => b.wins / b.usable - a.wins / a.usable);
    if (!rows.length) { neighbors.append(document.createTextNode(" · none")); return; }
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const text of ["Neighbor", "Agreement", "Usable", "Score", "Fresh-week age", "Status"]) {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = text; head.append(th);
    }
    const thead = document.createElement("thead"); thead.append(head); table.append(thead);
    const body = document.createElement("tbody");
    for (const e of rows) {
      const other = String(e.source) === focus ? String(e.target) : String(e.source);
      const row = document.createElement("tr");
      row.tabIndex = 0;
      row.dataset.peerId = other;
      row.setAttribute("aria-label", `Highlight ${nodes[indexById.get(other)]?.name ?? other} in the network`);
      row.addEventListener("pointerenter", () => { hoveredPeer = other; draw(); });
      row.addEventListener("pointerleave", () => { if (hoveredPeer === other) hoveredPeer = null; draw(); });
      row.addEventListener("focus", () => { focusedPeer = other; draw(); });
      row.addEventListener("blur", () => { if (focusedPeer === other) focusedPeer = null; draw(); });
      const peerNode = nodes[indexById.get(other)];
      for (const [column, text] of [peerNode?.name ?? other, e.wins, e.usable,
        `${(100 * e.wins / e.usable).toFixed(1)}%`, e.age,
        e.wins / e.usable < data.entry ? "Retained below entry" : "At or above entry"].entries()) {
        const td = document.createElement("td"); td.textContent = String(text);
        if (column === 0) {
          const category = categoryName(peerNode), detail = document.createElement("span"), swatch = document.createElement("span");
          detail.className = "pn-category"; detail.dataset.category = category;
          swatch.className = "pn-swatch"; swatch.setAttribute("aria-hidden", "true");
          swatch.style.setProperty("--swatch", categoryColor(category, window.matchMedia("(prefers-color-scheme: dark)").matches));
          detail.append(swatch, document.createTextNode(category)); td.append(detail);
        }
        row.append(td);
      }
      body.append(row);
    }
    table.append(body); neighbors.append(table);
    if (restorePeer) body.querySelectorAll("tr").forEach(row => {
      if (row.dataset.peerId === restorePeer) row.focus({preventScroll:true});
    });
    if (!rows.some(e => String(e.source) === focusedPeer || String(e.target) === focusedPeer)) focusedPeer = null;
    if (!rows.some(e => String(e.source) === hoveredPeer || String(e.target) === hoveredPeer)) hoveredPeer = null;
  }
  function canvasSize(canvas) {
    const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * dpr)), height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const ctx = canvas.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, rect.width, rect.height);
    return [ctx, rect.width, rect.height];
  }
  function colors() {
    const s = getComputedStyle(root);
    return Object.fromEntries(["fg","muted","grid","add","remove"].map(k => [k, s.getPropertyValue(`--${k}`).trim()]));
  }
  function position(p, width, height) {
    const scale = Math.min(width, height) * .45;
    return [width / 2 + p[0] * scale, height / 2 - p[1] * scale];
  }
  function currentPositions() {
    const target = data.weeks[week].positions;
    if (!target || !animation) return target;
    const t = clamp((performance.now() - animation.start) / animation.duration, 0, 1);
    const ease = t * t * (3 - 2 * t), from = data.weeks[animation.from].positions;
    return target.map((p,i) => [from[i][0] + (p[0]-from[i][0])*ease, from[i][1] + (p[1]-from[i][1])*ease]);
  }
  function layoutLabels(pos, ids, gained, lost, width, baseHeight, measure) {
    const labels = [], placed = [], soft = pos.map(([x,y],i) => {
      const r = String(nodes[i].id) === focus ? 10 : 6;
      return {x:x-r,y:y-r,w:2*r,h:2*r};
    });
    let height = baseHeight;
    const overlaps = (a,b) => a.x < b.x+b.w+2 && a.x+a.w+2 > b.x && a.y < b.y+b.h+2 && a.y+a.h+2 > b.y;
    const wrap = text => {
      const max = Math.max(40, Math.min(150, width-30)), lines = [];
      let line = "";
      for (const word of text.split(/\s+/)) {
        let part = word;
        while (part && measure.measureText(part).width > max) {
          let cut = 1;
          while (cut < part.length && measure.measureText(part.slice(0,cut+1)).width <= max) cut++;
          if (line) { lines.push(line); line = ""; }
          lines.push(part.slice(0,cut)); part = part.slice(cut);
        }
        if (!part) continue;
        const joined = line ? `${line} ${part}` : part;
        if (measure.measureText(joined).width > max && line) { lines.push(line); line = part; }
        else line = joined;
      }
      if (line) lines.push(line);
      return lines.length ? lines : [""];
    };
    // Focus is pinned; stable ID order and fixed candidate order limit label jitter.
    for (const id of ids) {
      const i = indexById.get(id); if (i == null || !pos[i]) continue;
      const text = `${gained.has(id) ? "+ " : lost.has(id) ? "− " : ""}${nodes[i].name}`;
      const lines = wrap(text), bw = Math.ceil(Math.max(...lines.map(s => measure.measureText(s).width)) + 8), bh = lines.length*15+4;
      const origin = pos[i].slice();
      const gap = id === focus ? 13 : 10;
      const candidates = (x,y) => [
        {x:x+gap,y:y-bh/2}, {x:x-bw-gap,y:y-bh/2},
        {x:clamp(x-bw/2,2,width-bw-2),y:y-bh-gap}, {x:clamp(x-bw/2,2,width-bw-2),y:y+gap},
        {x:x+gap,y:y-bh-5}, {x:x-bw-gap,y:y-bh-5},
        {x:x+gap,y:y+5}, {x:x-bw-gap,y:y+5}
      ].map((b,anchor) => ({...b,w:bw,h:bh,anchor}));
      const evaluate = (x,y) => {
        const r = id === focus ? 10 : 8;
        const dot = {x:x-r,y:y-r,w:2*r,h:2*r};
        let best = null, bestScore = Infinity;
        for (const box of candidates(x,y)) {
          if (box.x < 2 || box.y < 2 || box.x+box.w > width-2 || box.y+box.h > height-2) continue;
          if (placed.some(p => overlaps(box,p.box) || overlaps(box,p.dot) || overlaps(dot,p.box) || overlaps(dot,p.dot))) continue;
          if (box.anchor === labelAnchors.get(id)) return {box,dot,x,y};
          const score = soft.reduce((n,r,j) => n + (j !== i && overlaps(box,r) ? 1 : 0), 0);
          if (score < bestScore) { best = {box,dot,x,y}; bestScore = score; }
        }
        return best;
      };
      let choice = evaluate(...origin);
      if (!choice) {
        // A later group may fit at its original dot if an earlier label takes
        // another anchor. Keep all previously placed dots fixed while trying.
        for (const previous of placed) {
          const original = previous.box;
          for (const alternate of previous.candidates(previous.x,previous.y)) {
            if (alternate.anchor === original.anchor || alternate.x < 2 || alternate.y < 2 ||
                alternate.x+alternate.w > width-2 || alternate.y+alternate.h > height-2) continue;
            if (placed.some(other => other !== previous &&
                (overlaps(alternate,other.box) || overlaps(alternate,other.dot)))) continue;
            previous.box = alternate;
            choice = evaluate(...origin);
            if (choice) { labelAnchors.set(previous.id,alternate.anchor); break; }
          }
          if (choice) break;
          previous.box = original;
        }
      }
      if (!choice && id !== focus) {
        // Move only a peer whose original near-dot group cannot fit.
        for (let radius = 16; !choice; radius += 16) {
          if (radius > Math.hypot(width,height)+32) { height += Math.max(100,bh+24); radius = 0; continue; }
          const samples = Math.max(8, Math.ceil(2*Math.PI*radius/16));
          for (let k = 0; k < samples && !choice; k++) {
            const angle = k*2*Math.PI/samples, x = origin[0]+radius*Math.cos(angle), y = origin[1]+radius*Math.sin(angle);
            if (x < 8 || x > width-8 || y < 8 || y > height-8) continue;
            choice = evaluate(x,y);
          }
        }
      }
      // The first (pinned) group has no competing labels; allow vertical growth
      // for unusually tall wrapped names.
      while (!choice) { height += Math.max(100,bh+24); choice = evaluate(...origin); }
      pos[i] = [choice.x,choice.y];
      labelAnchors.set(id,choice.box.anchor);
      Object.assign(choice,{id,lines,candidates});
      placed.push(choice);
    }
    labels.push(...placed);
    return {labels,height};
  }
  function draw() {
    if (!data?.weeks.length) return;
    const w = graphWindow.clientWidth, h = clamp(window.innerWidth * .48, 360, 620);
    if (!w || !h) return;
    const current = data.weeks[week], color = colors();
    const target = current.positions;
    const edges = snapshots[week];
    const basePos = target && edges ? currentPositions().map(p => position(p, w, h)) : [];
    const neighborIds = new Set();
    if (focus && edges) for (const e of edges.values()) {
      if (String(e.source) === focus) neighborIds.add(String(e.target));
      if (String(e.target) === focus) neighborIds.add(String(e.source));
    }
    const delta = animation && focus ? focusedChanges(week) : null;
    const gained = new Set(delta?.gained ?? []), lost = new Set(delta?.lost ?? []);
    const peer = focusedPeer || hoveredPeer;
    const measure = graph.getContext("2d");
    measure.font = "600 12px system-ui";
    if (anchorFocus !== focus) { labelAnchors.clear(); anchorFocus = focus; }
    const ids = focus && basePos.length ? [focus, ...[...new Set([...neighborIds, ...lost])].filter(id => id !== focus).sort()] : [];
    const {labels,height} = layoutLabels(basePos, ids, gained, lost, w, h, measure);
    const pos = basePos.map(([x,y]) => [x*camera.scale+camera.x,y*camera.scale+camera.y]);
    displayedPositions = pos;
    graph.style.width = `${w}px`;
    graph.style.height = `${height}px`;
    const [ctx] = canvasSize(graph);
    if (!target || !snapshots[week]) {
      ctx.fillStyle = color.muted; ctx.font = "15px system-ui"; ctx.textAlign = "center";
      ctx.fillText("No computed snapshot for this week", w/2, h/2);
      drawTimeline(color); return;
    }
    ctx.textAlign = "left";
    const t = animation ? clamp((performance.now() - animation.start) / animation.duration, 0, 1) : 1;
    const previous = animation ? snapshots[animation.from] : null;
    function line(e, stroke, alpha, dash, width) {
      const [a,b] = edgeNodes(e); if (!pos[a] || !pos[b]) return;
      ctx.globalAlpha = alpha; ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(...pos[a]); ctx.lineTo(...pos[b]); ctx.stroke();
    }
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const incident = e => focus != null && (String(e.source) === focus || String(e.target) === focus);
    const highlighted = e => peer != null && incident(e) && (String(e.source) === peer || String(e.target) === peer);
    function edgeLine(e, selected) {
      const score = clamp((e.wins / e.usable - .5) / .4, 0, 1);
      const rgb = dark
        ? `rgb(${Math.round(255-89*score)},${Math.round(154-2*score)},${Math.round(102+153*score)})`
        : `rgb(${Math.round(211-107*score)},${Math.round(103-27*score)},${Math.round(55+137*score)})`;
      line(e, rgb, (.24 + .7 * Math.min(e.age / 8, 1)) * (selected ? 1 : .14), [], selected && focus ? 2 : 1.1);
    }
    for (const e of edges.values()) if (!incident(e)) edgeLine(e, focus == null);
    for (const e of edges.values()) if (incident(e) && !highlighted(e)) edgeLine(e, true);
    for (const e of edges.values()) if (highlighted(e)) line(e, color.fg, 1, [], 4);
    if (previous) for (const [key,e] of edges) if (!previous.has(key)) {
      line(e, color.add, (1-t) * (focus == null || incident(e) ? 1 : .18), [], 3);
    }
    if (previous) for (const [key,e] of previous) if (!edges.has(key)) {
      const selected = focus == null || incident(e);
      line(e, color.remove, (1-t) * (selected ? .9 : .15), [5,4], 2);
    }
    ctx.globalAlpha = 1; ctx.setLineDash([]);
    pos.forEach(([x,y],i) => {
      const id = String(nodes[i].id), selected = id === focus, neighbor = neighborIds.has(id);
      const changing = gained.has(id) || lost.has(id);
      const radius = selected ? 10 : changing ? 6 : neighbor ? 5 : 4;
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(x,y,radius,0,2*Math.PI);
      ctx.fillStyle = categoryColor(categoryName(nodes[i]), dark); ctx.fill();
      if (highlightedCategory === categoryName(nodes[i])) {
        ctx.strokeStyle = color.fg; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x,y,radius+3,0,2*Math.PI); ctx.stroke();
      }
      if (id === peer && neighbor) { ctx.strokeStyle = color.fg; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(x,y,9,0,2*Math.PI); ctx.stroke(); }
    });
    ctx.globalAlpha = 1;
    if (focus) {
      const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
      ctx.font = "600 12px system-ui"; ctx.textBaseline = "middle";
      for (const {id, lines, box:baseBox, x, y} of labels) {
        const box = {...baseBox,x:x*camera.scale+camera.x+baseBox.x-x,y:y*camera.scale+camera.y+baseBox.y-y};
        ctx.fillStyle = bg; ctx.fillRect(box.x,box.y,box.w,box.h);
        if (id === peer) { ctx.strokeStyle = color.fg; ctx.lineWidth = 2; ctx.strokeRect(box.x,box.y,box.w,box.h); }
        ctx.fillStyle = gained.has(id) ? color.add : lost.has(id) ? color.remove : color.fg;
        lines.forEach((text,i) => ctx.fillText(text,box.x+4,box.y+9+i*15));
      }
      ctx.textBaseline = "alphabetic";
    }
    drawTimeline(color);
  }
  function drawTimeline(color) {
    const [ctx,w,h] = canvasSize(timeline), n = data.weeks.length, mid = h/2;
    const max = Math.max(1, ...counts.filter(Boolean).flatMap(c => [c.added,c.removed]));
    const step = w / n, bar = Math.max(1, Math.min(10, step*.7));
    ctx.strokeStyle = color.grid; ctx.beginPath(); ctx.moveTo(0,mid); ctx.lineTo(w,mid); ctx.stroke();
    counts.forEach((c,i) => {
      if (!c) return; const x = (i+.5)*step;
      ctx.fillStyle = color.add; ctx.fillRect(x-bar/2, mid-c.added/max*(mid-5), bar, c.added/max*(mid-5));
      ctx.fillStyle = color.remove; ctx.fillRect(x-bar/2, mid, bar, c.removed/max*(mid-5));
    });
    ctx.strokeStyle = color.fg; ctx.lineWidth = 2; const x = (week+.5)*step;
    ctx.beginPath(); ctx.moveTo(x,2); ctx.lineTo(x,h-2); ctx.stroke();
  }
  function seek(i) {
    stop(); week = clamp(i, 0, data.weeks.length-1); update(); save();
  }
  function next() {
    if (!playing || week >= data.weeks.length - 1) { stop(); return; }
    const from = week; week++;
    if (snapshots[from] && snapshots[week]) {
      animation = {from, start:performance.now(), duration:650};
      update();
      const tick = () => {
        if (!playing || !animation) return;
        draw();
        if (performance.now() - animation.start < animation.duration) raf = requestAnimationFrame(tick);
        else { animation = null; draw(); save(); timer = setTimeout(next, 220); }
      };
      raf = requestAnimationFrame(tick);
    } else { animation = null; update(); save(); timer = setTimeout(next, 500); }
  }
  function pointWeek(event) {
    const r = timeline.getBoundingClientRect();
    return clamp(Math.floor((event.clientX-r.left) / r.width * data.weeks.length), 0, data.weeks.length-1);
  }
  const onPointer = e => { timeline.setPointerCapture(e.pointerId); seek(pointWeek(e)); };
  const onMove = e => { if (timeline.hasPointerCapture(e.pointerId)) seek(pointWeek(e)); };
  const onKey = e => {
    let i = week;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") i--;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") i++;
    else if (e.key === "Home") i = 0;
    else if (e.key === "End") i = data.weeks.length-1;
    else return;
    e.preventDefault(); seek(i);
  };
  const onGraph = e => {
    if (suppressClick) { suppressClick = false; return; }
    const positions = displayedPositions; if (!positions.length) return;
    const rect = graph.getBoundingClientRect(), x = e.clientX-rect.left, y = e.clientY-rect.top;
    let best = -1, distance = 14;
    positions.forEach(([px,py],i) => { const d = Math.hypot(px-x,py-y); if (d < distance) { best=i; distance=d; } });
    if (best >= 0) { focus = String(nodes[best].id); syncSearch(); update(); save(); }
  };
  function zoomAt(factor, x, y) {
    const scale = clamp(camera.scale * factor, .25, 5), ratio = scale / camera.scale;
    camera.x = x - (x-camera.x)*ratio;
    camera.y = y - (y-camera.y)*ratio;
    camera.scale = scale;
  }
  function graphPoint(e) {
    const r = graph.getBoundingClientRect();
    return {x:e.clientX-r.left,y:e.clientY-r.top};
  }
  const onGraphDown = e => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (!pointers.size) { suppressClick = false; gesture = {moved:false}; }
    pointers.set(e.pointerId,graphPoint(e));
    graph.setPointerCapture(e.pointerId);
    if (pointers.size > 1) { gesture.moved = true; suppressClick = true; }
  };
  const onGraphMove = e => {
    if (!pointers.has(e.pointerId)) return;
    const before = [...pointers.values()], old = pointers.get(e.pointerId), point = graphPoint(e);
    pointers.set(e.pointerId,point);
    if (before.length >= 2) {
      const after = [...pointers.values()], a = before[0], b = before[1], c = after[0], d = after[1];
      const oldDistance = Math.hypot(a.x-b.x,a.y-b.y), distance = Math.hypot(c.x-d.x,c.y-d.y);
      const oldCenter = {x:(a.x+b.x)/2,y:(a.y+b.y)/2}, center = {x:(c.x+d.x)/2,y:(c.y+d.y)/2};
      if (oldDistance > 0) zoomAt(distance/oldDistance,oldCenter.x,oldCenter.y);
      camera.x += center.x-oldCenter.x; camera.y += center.y-oldCenter.y;
      gesture.moved = suppressClick = true; draw();
    } else {
      const dx = point.x-old.x, dy = point.y-old.y;
      if (!gesture.moved) {
        gesture.dx = (gesture.dx || 0) + dx; gesture.dy = (gesture.dy || 0) + dy;
        if (Math.hypot(gesture.dx,gesture.dy) < 4) return;
        camera.x += gesture.dx; camera.y += gesture.dy;
      } else { camera.x += dx; camera.y += dy; }
      gesture.moved = suppressClick = true; draw();
    }
  };
  const onGraphUp = e => {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (graph.hasPointerCapture(e.pointerId)) graph.releasePointerCapture(e.pointerId);
    if (!pointers.size) gesture = null;
  };
  const onGraphWheel = e => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const p = graphPoint(e), unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? graph.clientHeight : 1;
    zoomAt(Math.exp(-e.deltaY*unit*.002),p.x,p.y); draw();
  };
  const onGraphKey = e => {
    const movement = {ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]}[e.key];
    if (!movement) return;
    e.preventDefault(); camera.x += movement[0]; camera.y += movement[1]; draw();
  };
  const zoomCenter = factor => { zoomAt(factor,graph.clientWidth/2,graph.clientHeight/2); draw(); };
  const onZoomIn = () => zoomCenter(1.25), onZoomOut = () => zoomCenter(1/1.25);
  const onFit = () => { camera.scale = 1; camera.x = camera.y = 0; draw(); };
  const onSearch = () => {
    const value = search.value.trim().toLocaleLowerCase();
    if (!value) { focus = null; update(); save(); return; }
    const matches = nodes.filter(n => `${n.name} (${n.id})`.toLocaleLowerCase() === value || n.name.toLocaleLowerCase() === value || String(n.id) === value);
    if (matches.length === 1) {
      const nextFocus = String(matches[0].id);
      if (nextFocus === focus) { syncSearch(); return; }
      focus = nextFocus; syncSearch(); update(); save();
    }
  };
  const onPlay = () => {
    if (playing) { stop(); update(); save(); return; }
    const restart = week >= data.weeks.length-1;
    if (restart) week = 0;
    playing = true; play.textContent = "Pause"; play.setAttribute("aria-label","Pause"); update();
    if (restart) { save(); timer = setTimeout(next, 220); } else next();
  };
  const onClear = () => { focus = null; syncSearch(); update(); save(); };
  const onPayload = () => setup(model.get("payload"), model.get("view_state"));
  timeline.addEventListener("pointerdown",onPointer); timeline.addEventListener("pointermove",onMove);
  timeline.addEventListener("keydown",onKey); graph.addEventListener("click",onGraph);
  graph.addEventListener("pointerdown",onGraphDown); graph.addEventListener("pointermove",onGraphMove);
  graph.addEventListener("pointerup",onGraphUp); graph.addEventListener("pointercancel",onGraphUp);
  graph.addEventListener("wheel",onGraphWheel,{passive:false}); graph.addEventListener("keydown",onGraphKey);
  zoomIn.addEventListener("click",onZoomIn); zoomOut.addEventListener("click",onZoomOut); fit.addEventListener("click",onFit);
  search.addEventListener("change",onSearch); play.addEventListener("click",onPlay); clear.addEventListener("click",onClear);
  model.on("change:payload",onPayload);
  const observer = new ResizeObserver(() => draw()); observer.observe(graphWindow); observer.observe(timeline);
  const theme = window.matchMedia("(prefers-color-scheme: dark)"), onTheme = () => { updateLegend(); draw(); };
  theme.addEventListener("change",onTheme);
  setup(model.get("payload"), model.get("view_state"));
  return () => {
    if (saveTimer) { clearTimeout(saveTimer); model.save_changes(); }
    disposed = true; stop(); observer.disconnect(); theme.removeEventListener("change",onTheme);
    model.off("change:payload",onPayload);
    timeline.removeEventListener("pointerdown",onPointer); timeline.removeEventListener("pointermove",onMove);
    timeline.removeEventListener("keydown",onKey); graph.removeEventListener("click",onGraph);
    graph.removeEventListener("pointerdown",onGraphDown); graph.removeEventListener("pointermove",onGraphMove);
    graph.removeEventListener("pointerup",onGraphUp); graph.removeEventListener("pointercancel",onGraphUp);
    graph.removeEventListener("wheel",onGraphWheel); graph.removeEventListener("keydown",onGraphKey);
    zoomIn.removeEventListener("click",onZoomIn); zoomOut.removeEventListener("click",onZoomOut); fit.removeEventListener("click",onFit);
    search.removeEventListener("change",onSearch); play.removeEventListener("click",onPlay); clear.removeEventListener("click",onClear);
  };
}
export default { render };
