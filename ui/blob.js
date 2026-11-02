/* Cells theme: weighted-Voronoi layout engine (d3-voronoi-map, BSD-3, vendored in ui/vendor).
   Cells get an area proportional to their weight, are inset to leave gutters, and get rounded,
   incircle-capped corners. Hover "breathes" a cell by tweening between two solved diagrams
   (base <-> hovered), so repeated hovers never drift the layout. */
(() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // deterministic PRNG (mulberry32) so the same tiles + size always give the same layout
  const prng = seed => () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  /* items: [{id, weight}] in reading order. init: {id: {x, y, weight}} for a warm start. */
  function solve(items, W, H, pad, init) {
    const clip = [[pad, pad], [pad, H - pad], [W - pad, H - pad], [W - pad, pad]];
    const n = items.length, cols = Math.max(1, Math.round(Math.sqrt((n * W) / H))), rows = Math.ceil(n / cols);
    const rnd = prng(7);
    const seedPos = (d, i) => {
      if (init && init[d.id]) return [init[d.id].x, init[d.id].y];
      const cx = (i % cols) + 0.5 + (rnd() - 0.5) * 0.35, cy = Math.floor(i / cols) + 0.5 + (rnd() - 0.5) * 0.35;
      return [pad + (cx * (W - 2 * pad)) / cols, pad + (cy * (H - 2 * pad)) / rows];
    };
    const sim = d3.voronoiMapSimulation(items).weight(d => d.weight).clip(clip).prng(rnd)
      .convergenceRatio(0.003).maxIterationCount(260).minWeightRatio(0.02).initialPosition(seedPos).stop();
    if (init) {
      const ws = Object.values(init).map(s => s.weight), avg = ws.reduce((a, b) => a + b, 0) / (ws.length || 1) || 1;
      sim.initialWeight(d => (init[d.id] && init[d.id].weight > 0 ? init[d.id].weight : avg));
    }
    let s = sim.state();
    while (!s.ended) { sim.tick(); s = sim.state(); }
    const sites = {};
    for (const p of s.polygons) { const m = p.site.originalObject; sites[m.data.originalData.id] = { x: m.x, y: m.y, weight: m.weight }; }
    return { sites, clip };
  }

  function diagram(sites, clip) {
    const arr = Object.entries(sites).map(([id, s]) => ({ id, ...s }));
    const polys = d3.weightedVoronoi().x(d => d.x).y(d => d.y).weight(d => d.weight).clip(clip)(arr);
    const out = {};
    for (const p of polys) out[p.site.originalObject.id] = p.map(q => [q[0], q[1]]);
    return out;
  }

  /* inset a convex polygon by d (moves every edge inward) */
  function inset(poly, d) {
    const pts = poly.filter((p, i) => Math.hypot(p[0] - poly[(i + 1) % poly.length][0], p[1] - poly[(i + 1) % poly.length][1]) > 0.5);
    const n = pts.length; if (n < 3) return [];
    const c = d3.polygonCentroid(pts);
    const lines = pts.map((p, i) => {
      const q = pts[(i + 1) % n], dx = q[0] - p[0], dy = q[1] - p[1], L = Math.hypot(dx, dy);
      let nx = -dy / L, ny = dx / L;
      if ((c[0] - p[0]) * nx + (c[1] - p[1]) * ny < 0) { nx = -nx; ny = -ny; }
      return { x: p[0] + nx * d, y: p[1] + ny * d, dx, dy };
    });
    const out = [];
    for (let i = 0; i < n; i++) {
      const a = lines[(i - 1 + n) % n], b = lines[i], cr = a.dx * b.dy - a.dy * b.dx;
      if (Math.abs(cr) < 1e-9) { out.push([b.x, b.y]); continue; }
      const t = ((b.x - a.x) * b.dy - (b.y - a.y) * b.dx) / cr;
      out.push([a.x + a.dx * t, a.y + a.dy * t]);
    }
    // collapsed cell: inset flipped orientation or vanished
    return Math.sign(d3.polygonArea(out)) === Math.sign(d3.polygonArea(pts)) && Math.abs(d3.polygonArea(out)) > 40 ? out : [];
  }

  /* rounded path; corner cut t is capped at 45% of the shorter neighbouring edge */
  function roundedPath(poly, r, ox, oy) {
    const n = poly.length, f = v => v.toFixed(1);
    const corner = i => {
      const v = poly[i], a = poly[(i - 1 + n) % n], b = poly[(i + 1) % n];
      const la = Math.hypot(a[0] - v[0], a[1] - v[1]), lb = Math.hypot(b[0] - v[0], b[1] - v[1]);
      const cos = ((a[0] - v[0]) * (b[0] - v[0]) + (a[1] - v[1]) * (b[1] - v[1])) / (la * lb);
      const half = Math.acos(Math.max(-1, Math.min(1, cos))) / 2;
      const t = Math.min(r / Math.tan(half || 1e-3), la * 0.45, lb * 0.45);
      return { v, p1: [v[0] + ((a[0] - v[0]) / la) * t, v[1] + ((a[1] - v[1]) / la) * t], p2: [v[0] + ((b[0] - v[0]) / lb) * t, v[1] + ((b[1] - v[1]) / lb) * t] };
    };
    const cs = poly.map((_, i) => corner(i)), last = cs[n - 1];
    let d = `M${f(last.p2[0] - ox)} ${f(last.p2[1] - oy)}`;
    for (const c of cs) d += `L${f(c.p1[0] - ox)} ${f(c.p1[1] - oy)}Q${f(c.v[0] - ox)} ${f(c.v[1] - oy)} ${f(c.p2[0] - ox)} ${f(c.p2[1] - oy)}`;
    return d + "Z";
  }

  /* largest axis-aligned rectangle inside a convex polygon (searched around the centroid) */
  function contentBox(poly) {
    if (poly.length < 3) return null;
    const c = d3.polygonCentroid(poly), xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
    const bw = Math.max(...xs) - Math.min(...xs), bh = Math.max(...ys) - Math.min(...ys);
    let best = null;
    for (const ox of [-0.1, -0.05, 0, 0.05, 0.1]) for (const oy of [-0.1, -0.05, 0, 0.05, 0.1]) {
      const cx = c[0] + ox * bw, cy = c[1] + oy * bh;
      if (!d3.polygonContains(poly, [cx, cy])) continue;
      for (const a of [0.7, 1, 1.35, 1.8, 2.4]) {
        const sa = Math.sqrt(a); let lo = 0, hi = Math.max(bw, bh) * 1.5;
        for (let k = 0; k < 16; k++) {
          const m = (lo + hi) / 2, w = m * sa, h = m / sa;
          const ok = [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]].every(p => d3.polygonContains(poly, p));
          if (ok) lo = m; else hi = m;
        }
        const w = lo * sa, h = lo / sa, score = w * h * (1 - Math.abs(Math.log(a)) * 0.06);
        if (!best || score > best.score) best = { x: cx - w / 2, y: cy - h / 2, w, h, score };
      }
    }
    return best;
  }

  const lerp = (a, b, t) => a + (b - a) * t;
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const spring = t => 1 + 2.2 * Math.pow(t - 1, 3) + 1.2 * Math.pow(t - 1, 2); // easeOutBack-ish, gentle overshoot

  const C = { el: null, items: [], opts: null, base: null, cur: null, hover: {}, boxes: {}, raf: 0, hovered: null, W: 0, H: 0 };

  function draw(sites, withBoxes) {
    const polys = diagram(sites, C.base.clip), pad = C.opts.gap / 2;
    for (const it of C.items) {
      const el = C.tiles[it.id]; if (!el) continue;
      const raw = polys[it.id], poly = raw ? inset(raw, pad) : [];
      if (!poly.length) { el.style.visibility = "hidden"; continue; }
      el.style.visibility = "";
      const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
      const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0, h = Math.max(...ys) - y0;
      const r = C.opts.radius * ({ soft: 1, round: 2.4, sharp: 0.3 }[it.shape] || 1);
      Object.assign(el.style, { left: x0 + "px", top: y0 + "px", width: w + "px", height: h + "px", clipPath: `path("${roundedPath(poly, r, x0, y0)}")` });
      if (withBoxes || !C.boxes[it.id]) {
        const inner = inset(raw, pad + Math.max(10, Math.min(22, r * 0.35)) + 6);
        C.boxes[it.id] = contentBox(inner.length ? inner : poly) || { x: x0, y: y0, w, h };
      }
      const b = C.boxes[it.id];
      el.style.setProperty("--bx", b.x - x0 + "px"); el.style.setProperty("--by", b.y - y0 + "px");
      el.style.setProperty("--bw", b.w + "px"); el.style.setProperty("--bh", b.h + "px");
    }
  }

  function tween(to, ms, ease, done) {
    cancelAnimationFrame(C.raf);
    const from = C.cur || to, t0 = performance.now();
    if (reduced || ms <= 0) { C.cur = to; draw(to, true); done && done(); return; }
    const step = now => {
      const t = Math.min(1, (now - t0) / ms), k = ease(t), mid = {};
      for (const id in to) {
        const a = from[id] || to[id], b = to[id];
        mid[id] = { x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), weight: lerp(a.weight, b.weight, k) };
      }
      C.cur = mid; draw(mid, t === 1);
      if (t < 1) C.raf = requestAnimationFrame(step); else { C.cur = to; done && done(); }
    };
    C.raf = requestAnimationFrame(step);
  }

  /* public: lay out tiles inside the grid element. items: [{id, weight, shape}] */
  function layout(el, items, opts, animate) {
    C.el = el; C.items = items; C.opts = opts; C.hover = {}; C.hovered = null;
    C.tiles = Object.fromEntries([...el.querySelectorAll(".tile")].map(t => [t.dataset.id, t]));
    C.W = el.clientWidth; C.H = el.clientHeight;
    if (C.W < 50 || C.H < 50 || !items.length) return;
    try { C.base = solve(items, C.W, C.H, opts.gap / 2, null); }
    catch (e) { C.base = solve(items, C.W, C.H, opts.gap / 2, null); } // ponytail: rare d3VoronoiMapError; seeds are deterministic, so a retry only helps if size changed meanwhile
    C.boxes = {};
    const prev = C.cur && Object.keys(C.cur).every(id => C.base.sites[id]) ? C.cur : null;
    if (animate && prev) { C.cur = prev; tween(C.base.sites, 560, spring); }
    else { C.cur = C.base.sites; draw(C.cur, true); }
  }

  function hover(id) {
    if (reduced || !C.base || C.hovered === id) return;
    C.hovered = id;
    if (!id) return tween(C.base.sites, 460, easeOut);
    if (!C.hover[id]) {
      const items = C.items.map(it => ({ ...it, weight: it.id === id ? it.weight * 1.28 : it.weight }));
      try { C.hover[id] = solve(items, C.W, C.H, C.opts.gap / 2, C.base.sites).sites; } catch (e) { return; }
    }
    tween(C.hover[id], 420, spring);
  }

  function reset() { cancelAnimationFrame(C.raf); C.cur = null; C.base = null; }

  // goo filter (blur + alpha threshold) shared by the liquid controls
  document.addEventListener("DOMContentLoaded", () => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("width", "0"); s.setAttribute("height", "0"); s.setAttribute("aria-hidden", "true");
    s.style.position = "absolute";
    s.innerHTML = `<filter id="goo"><feGaussianBlur in="SourceGraphic" stdDeviation="5" result="b"/>
      <feColorMatrix in="b" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9" result="g"/>
      <feComposite in="SourceGraphic" in2="g" operator="atop"/></filter>`;
    document.body.prepend(s);
  });

  window.Cells = { layout, hover, reset, _inset: inset, _contentBox: contentBox, _state: C };
})();
