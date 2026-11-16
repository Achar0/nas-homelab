// Interactive homelab map: plain SVG + vanilla JS, no build step.
(() => {
  "use strict";
  const D = window.HOMELAB;
  const NS = "http://www.w3.org/2000/svg";
  const W = 1800, H = 1080;          // world size
  const NW = 200, NH = 58;           // node card size
  // Grid: cards sit in cells; lines only travel through the gaps between cells.
  const COLW = 300, ROWH = 120;      // cell pitch (gaps: 100 wide, 62 tall)
  const PAD = 16, HEAD = 40;         // section panel padding and label height
  const LANE = 8;                    // distance between parallel lines in a gap
  const colX = (c) => 150 + c * COLW;
  const rowY = (r) => 210 + r * ROWH + (r >= 5 ? 70 : 0);   // storage rows get extra space above
  const $ = (s) => document.querySelector(s);
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 24×24 stroke icons
  const ICONS = {
    globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z",
    phone: "M8 3h8a1.5 1.5 0 0 1 1.5 1.5v15A1.5 1.5 0 0 1 16 21H8a1.5 1.5 0 0 1-1.5-1.5v-15A1.5 1.5 0 0 1 8 3zM11 18h2",
    router: "M4 14h16v5H4zM7.5 16.5h.01M11 16.5h.01M8 14l-2-6M16 14l2-6M9.5 8.5a4 4 0 0 1 5 0M7.5 6a7 7 0 0 1 9 0",
    laptop: "M5 6h14v9H5zM3 18h18",
    tv: "M3 6h18v11H3zM8 21h8M12 17v4",
    tunnel: "M4 19V11a8 8 0 0 1 16 0v8M8 19v-7a4 4 0 0 1 8 0v7",
    lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3M12 15v2",
    shield: "M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6l7-3zM9 12l2 2 4-4",
    home: "M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-5h4v5",
    radar: "M12 12l6-6M12 3a9 9 0 1 0 9 9M12 7.5A4.5 4.5 0 1 0 16.5 12",
    chart: "M4 20V4M4 20h16M8 16v-4M12 16V8M16 16v-6",
    pulse: "M3 12h4l2-5 4 10 2-5h6",
    download: "M12 4v11M7 10l5 5 5-5M5 20h14",
    rss: "M5 5a14 14 0 0 1 14 14M5 11a8 8 0 0 1 8 8M6 18h.01",
    film: "M4 4h16v16H4zM8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4",
    db: "M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3zM5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3",
    box: "M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zM4 7.5l8 4.5 8-4.5M12 12v9",
    gauge: "M4.5 17a8.5 8.5 0 1 1 15 0M12 13l4-4",
    cpu: "M7 7h10v10H7zM10 10h4v4h-4zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
    layers: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
    server: "M4 4h16v7H4zM4 13h16v7H4zM7.5 7.5h.01M7.5 16.5h.01M12 7.5h5M12 16.5h5",
    drive: "M3 14l3-9h12l3 9M3 14h18v5H3zM7 16.5h.01M11 16.5h.01",
    disk: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM14 14l4 4",
    chip: "M4 8h16v8H4zM7 8V5M11 8V5M15 8V5M7 16v3M11 16v3M15 16v3",
  };

  // ---------- helpers ----------
  const el = (tag, attrs = {}, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };
  const byId = Object.fromEntries(D.nodes.map((n) => [n.id, n]));
  D.nodes.forEach((n) => { n.x = colX(n.col); n.y = rowY(n.row); });
  const occ = {};
  D.nodes.forEach((n) => { occ[n.col + "," + n.row] = n; });
  const maxCol = Math.max(...D.nodes.map((n) => n.col)), maxRow = Math.max(...D.nodes.map((n) => n.row));
  const linkColor = (t) => `stroke: var(--l-${t})`;

  // ---------- build the SVG ----------
  const svg = $("#map");
  const defs = el("defs", {}, svg);
  const pat = el("pattern", { id: "dots", width: 28, height: 28, patternUnits: "userSpaceOnUse" }, defs);
  el("circle", { class: "grid-dot", cx: 1, cy: 1, r: 1 }, pat);

  const root = el("g", { class: "map" }, svg);
  el("rect", { fill: "url(#dots)", x: -4000, y: -4000, width: W + 8000, height: H + 8000 }, root);
  const gGroups = el("g", {}, root);
  const gLinks = el("g", {}, root);
  const gNodes = el("g", {}, root);
  const gFx = el("g", {}, root);

  // Sections: one soft panel each, label inside; the gaps between panels show what belongs where.
  const regionBox = (g) => ({
    x: colX(g.c0) - NW / 2 - PAD, y: rowY(g.r0) - NH / 2 - HEAD,
    w: colX(g.c1) - colX(g.c0) + NW + 2 * PAD, h: rowY(g.r1) - rowY(g.r0) + NH + HEAD + PAD,
  });
  for (const g of D.groups) {
    const b = regionBox(g);
    el("rect", { class: "region", x: b.x, y: b.y, width: b.w, height: b.h, rx: 22 }, gGroups);
    el("text", { class: "region-label", x: b.x + 18, y: b.y + 26 }, gGroups).textContent = g.label;
  }
  {
    // The NAS sections share one title above them
    const parts = D.groups.filter((g) => g.part === "nas").map(regionBox);
    const x = Math.min(...parts.map((b) => b.x)), y = Math.min(...parts.map((b) => b.y));
    el("text", { class: "region-title", x: x + 4, y: y - 34 }, gGroups).textContent = D.nas.title;
    el("text", { class: "region-sub", x: x + 4, y: y - 12 }, gGroups).textContent = D.nas.note;
  }
  // Each node's section, shown as the tag in the detail card
  const groupOf = (n) => D.groups.find((g) => n.col >= g.c0 && n.col <= g.c1 && n.row >= g.r0 && n.row <= g.r1);

  // ---------- line routing ----------
  // Every line runs horizontally/vertically through the gaps, each in its own lane,
  // with rounded corners, so it can be followed by eye from end to end.
  const vGapX = (g) => colX(g) + COLW / 2;                 // gap right of column g
  const hGapY = (r) => (rowY(r) + rowY(r + 1)) / 2;        // gap below row r
  const emptyBetweenRows = (c, r1, r2) => { for (let r = Math.min(r1, r2) + 1; r < Math.max(r1, r2); r++) if (occ[c + "," + r]) return false; return true; };
  const emptyBetweenCols = (r, c1, c2) => { for (let c = Math.min(c1, c2) + 1; c < Math.max(c1, c2); c++) if (occ[c + "," + r]) return false; return true; };

  function plan(l) {
    const A = byId[l.a], B = byId[l.b], dc = B.col - A.col, dr = B.row - A.row;
    if (dc === 0 && emptyBetweenRows(A.col, A.row, B.row)) {
      return { kind: "v", sideA: dr > 0 ? "bottom" : "top", sideB: dr > 0 ? "top" : "bottom" };
    }
    if (dc === 0) {
      const right = A.col < maxCol, side = right ? "right" : "left";
      return { kind: "same", sideA: side, sideB: side, gA: right ? A.col : A.col - 1 };
    }
    const s = Math.sign(dc), sideA = s > 0 ? "right" : "left", sideB = s > 0 ? "left" : "right";
    const gA = s > 0 ? A.col : A.col - 1, gB = s > 0 ? B.col - 1 : B.col;
    if (gA === gB || (dr === 0 && emptyBetweenCols(A.row, A.col, B.col))) return { kind: "z", sideA, sideB, gA };
    let hr = dr > 0 ? A.row : dr < 0 ? A.row - 1 : (A.row < maxRow ? A.row : A.row - 1);
    hr = Math.max(0, Math.min(maxRow - 1, hr));
    return { kind: "g", sideA, sideB, gA, gB, hr };
  }

  // Lines leaving the same side of a card get separate ports, ordered by where they head.
  function assignPorts(links) {
    const sides = {};
    for (const l of links) {
      const A = byId[l.a], B = byId[l.b], p = l.plan;
      const head = (other) => p.kind === "g" ? hGapY(p.hr) : other.y;
      (sides[l.a + p.sideA] ||= []).push({ l, end: "A", key: p.sideA.match(/top|bottom/) ? B.x : head(B) });
      (sides[l.b + p.sideB] ||= []).push({ l, end: "B", key: p.sideB.match(/top|bottom/) ? A.x : head(A) });
    }
    for (const [k, list] of Object.entries(sides)) {
      list.sort((a, b) => a.key - b.key);
      const vertical = /top|bottom/.test(k), n = list.length;
      const step = vertical ? 18 : Math.min(12, 40 / Math.max(1, n - 1));
      list.forEach((e, i) => { e.l["off" + e.end] = (i - (n - 1) / 2) * step; });
    }
  }
  function port(n, side, off) {
    if (side === "right") return [n.x + NW / 2, n.y + off];
    if (side === "left") return [n.x - NW / 2, n.y + off];
    if (side === "bottom") return [n.x + off, n.y + NH / 2];
    return [n.x + off, n.y - NH / 2];
  }

  // Lane allocation: within each gap, a line takes the lane nearest the centre that is free over its span.
  function takeLane(lanes, key, a, b) {
    const lo = Math.min(a, b) - 10, hi = Math.max(a, b) + 10;
    const used = (lanes[key] ||= {});
    for (let i = 0; i < 40; i++) {
      const idx = i % 2 ? (i + 1) / 2 : -i / 2;
      const iv = (used[idx] ||= []);
      if (iv.every(([x, y]) => hi < x || lo > y)) { iv.push([lo, hi]); return idx * LANE; }
    }
    return 0;
  }

  function routeLinks(links, lanes) {
    for (const l of links) {
      const A = byId[l.a], B = byId[l.b], p = l.plan;
      const pA = port(A, p.sideA, l.offA), pB = port(B, p.sideB, l.offB);
      let pts;
      if (p.kind === "v") pts = [pA, pB];
      else if (p.kind === "same" || p.kind === "z") {
        const x = vGapX(p.gA) + takeLane(lanes, "v" + p.gA, pA[1], pB[1]);
        pts = [pA, [x, pA[1]], [x, pB[1]], pB];
      } else {
        const y = hGapY(p.hr) + takeLane(lanes, "h" + p.hr, vGapX(p.gA), vGapX(p.gB));
        const xa = vGapX(p.gA) + takeLane(lanes, "v" + p.gA, pA[1], y);
        const xb = vGapX(p.gB) + takeLane(lanes, "v" + p.gB, y, pB[1]);
        pts = [pA, [xa, pA[1]], [xa, y], [xb, y], [xb, pB[1]], pB];
      }
      l.geom = rounded(pts);
    }
  }

  function rounded(pts, r = 10) {
    const P = [];
    for (const p of pts) { const q = P[P.length - 1]; if (!q || Math.abs(q[0] - p[0]) > 0.5 || Math.abs(q[1] - p[1]) > 0.5) P.push(p); }
    for (let i = P.length - 2; i > 0; i--) {     // drop points in the middle of a straight run
      const [a, b, c] = [P[i - 1], P[i], P[i + 1]];
      if ((Math.abs(a[0] - b[0]) < 0.5 && Math.abs(b[0] - c[0]) < 0.5) || (Math.abs(a[1] - b[1]) < 0.5 && Math.abs(b[1] - c[1]) < 0.5)) P.splice(i, 1);
    }
    let d = `M${P[0]}`, best = null, bestLen = -1;
    for (let i = 1; i < P.length; i++) {
      const len = Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
      if (len > bestLen) { bestLen = len; best = [P[i - 1], P[i]]; }
    }
    for (let i = 1; i < P.length - 1; i++) {
      const [a, b, c] = [P[i - 1], P[i], P[i + 1]];
      const l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
      const rr = Math.min(r, l1 / 2, l2 / 2);
      const p1 = [b[0] + (a[0] - b[0]) / l1 * rr, b[1] + (a[1] - b[1]) / l1 * rr];
      const p2 = [b[0] + (c[0] - b[0]) / l2 * rr, b[1] + (c[1] - b[1]) / l2 * rr];
      d += ` L${p1} Q${b} ${p2}`;
    }
    d += ` L${P[P.length - 1]}`;
    // Label on the middle of the longest straight run
    const vertical = Math.abs(best[0][0] - best[1][0]) < 0.5;
    const label = { x: (best[0][0] + best[1][0]) / 2 + (vertical ? 6 : 0), y: (best[0][1] + best[1][1]) / 2 - (vertical ? 0 : 5), anchor: vertical ? "start" : "middle" };
    return { d, label };
  }

  for (const l of D.links) {
    l.plan = plan(l);
    const g = el("g", { class: "lg", "data-type": l.type }, gLinks);
    l.path = el("path", { class: "link", style: linkColor(l.type) }, g);
    if (!reduceMotion) l.flowPath = el("path", { class: "link-flow", style: linkColor(l.type) }, g);
    if (l.label) { l.text = el("text", { class: "link-label" }, g); l.text.textContent = l.label; }
    l.g = g;
  }
  assignPorts(D.links);

  // Lines visible by default are routed first so they get the central lanes; the rest
  // (quiet or switched off) take the outer lanes and appear only on focus.
  function reroute(isShown) {
    const lanes = {};
    routeLinks(D.links.filter(isShown), lanes);
    routeLinks(D.links.filter((l) => !isShown(l)), lanes);
    for (const l of D.links) {
      l.path.setAttribute("d", l.geom.d);
      if (l.flowPath) l.flowPath.setAttribute("d", l.geom.d);
      if (l.text) { l.text.setAttribute("x", l.geom.label.x); l.text.setAttribute("y", l.geom.label.y); l.text.setAttribute("text-anchor", l.geom.label.anchor); }
    }
  }

  // Nodes
  for (const n of D.nodes) {
    const g = el("g", {
      class: "node", transform: `translate(${n.x - NW / 2},${n.y - NH / 2})`,
      tabindex: 0, role: "button", "data-id": n.id, "aria-label": `${n.label}, ${n.sub}`,
    }, gNodes);
    el("rect", { class: "card", width: NW, height: NH, rx: 12 }, g);
    el("rect", { class: "ico-bg", x: 10, y: 11, width: 36, height: 36, rx: 9 }, g);
    el("path", { class: "ico", d: ICONS[n.icon] || ICONS.box, transform: "translate(16,17)" }, g);
    el("text", { class: "title", x: 56, y: 26 }, g).textContent = n.label;
    el("text", { class: "sub", x: 56, y: 43 }, g).textContent = n.sub;
    el("circle", { class: "led-dot", cx: NW - 14, cy: 14, r: 3.5 }, g);
    n.g = g;
  }

  // ---------- view: pan and zoom ----------
  const view = { x: 0, y: 0, k: 1 };
  const apply = () => root.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
  const clampK = (k) => Math.min(3, Math.max(0.12, k));

  function safeBox() {
    // Viewport area not covered by the top and bottom bars.
    const r = svg.getBoundingClientRect();
    const top = ($(".bar.top").getBoundingClientRect().bottom || 0) + 12;
    const bottom = r.height - 70;
    return { x: 16, y: top, w: r.width - 32, h: Math.max(100, bottom - top) };
  }

  function fit(animate = true) {
    const b = safeBox();
    const k = clampK(Math.min(b.w / (W - 40), b.h / (H - 40)));
    const target = { k, x: b.x + (b.w - W * k) / 2, y: b.y + (b.h - H * k) / 2 };
    animateTo(target, animate);
  }

  let anim = 0;
  function animateTo(t, animate = true) {
    cancelAnimationFrame(anim);
    if (!animate || reduceMotion) { Object.assign(view, t); apply(); return; }
    const s = { ...view }, t0 = performance.now(), dur = 380;
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      view.x = s.x + (t.x - s.x) * e; view.y = s.y + (t.y - s.y) * e; view.k = s.k + (t.k - s.k) * e;
      apply();
      if (p < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  }

  function zoomAt(factor, cx, cy, animate = false) {
    const k = clampK(view.k * factor);
    const f = k / view.k;
    animateTo({ k, x: cx - (cx - view.x) * f, y: cy - (cy - view.y) * f }, animate);
  }
  const center = () => { const r = svg.getBoundingClientRect(); return [r.width / 2, r.height / 2]; };

  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
    zoomAt(factor, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  // Pointer drag (one finger / mouse) and pinch (two fingers)
  const pointers = new Map();
  let dragged = false, last = null, pinch = null;
  svg.addEventListener("pointerdown", (e) => {
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    svg.setPointerCapture(e.pointerId);
    dragged = false; last = [e.clientX, e.clientY];
    if (pointers.size === 2) {
      const [p, q] = [...pointers.values()];
      pinch = { d: Math.hypot(p[0] - q[0], p[1] - q[1]), k: view.k };
    }
  });
  svg.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 2 && pinch) {
      const [p, q] = [...pointers.values()];
      const r = svg.getBoundingClientRect();
      const d = Math.hypot(p[0] - q[0], p[1] - q[1]);
      zoomAt((pinch.k * d / pinch.d) / view.k, (p[0] + q[0]) / 2 - r.left, (p[1] + q[1]) / 2 - r.top);
      dragged = true;
      return;
    }
    const dx = e.clientX - last[0], dy = e.clientY - last[1];
    if (!dragged && Math.hypot(dx, dy) < 4) return;
    dragged = true; svg.classList.add("dragging");
    view.x += dx; view.y += dy; last = [e.clientX, e.clientY];
    cancelAnimationFrame(anim); apply();
  });
  const up = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 1) last = [...pointers.values()][0];
    if (!pointers.size) svg.classList.remove("dragging");
    // Clicks on nodes: handled here, so a drag never counts as a click.
    if (!dragged && e.type === "pointerup") {
      const target = document.elementFromPoint(e.clientX, e.clientY);
      const node = target && target.closest(".node");
      if (node) activate(node.dataset.id);
      else if (target && target.closest("#map")) select(null);
    }
  };
  svg.addEventListener("pointerup", up);
  svg.addEventListener("pointercancel", up);

  // ---------- failure model ----------
  const failed = new Set();
  let status = {};

  function computeStatus(set = failed) {
    const s = {};
    for (const n of D.nodes) s[n.id] = set.has(n.id) ? "failed" : "ok";
    const bad = (id) => s[id] === "failed" || s[id] === "down";
    // Propagate until nothing changes (the dependency graph is small).
    for (let i = 0; i < D.nodes.length; i++) {
      let changed = false;
      for (const n of D.nodes) {
        if (s[n.id] === "failed") continue;
        let next = "ok";
        const needs = n.needs || [];
        if (needs.some((r) => Array.isArray(r) ? r.every(bad) : bad(r))) next = "down";
        else if ((n.soft || []).some(bad)) next = "degraded";
        if (next !== s[n.id]) { s[n.id] = next; changed = true; }
      }
      if (!changed) break;
    }
    return s;
  }

  function render() {
    status = computeStatus();
    for (const n of D.nodes) {
      n.g.classList.remove("ok", "degraded", "down", "failed");
      n.g.classList.add(status[n.id]);
    }
    for (const l of D.links) {
      const dead = ["failed", "down"].includes(status[l.a]) || ["failed", "down"].includes(status[l.b]);
      l.g.classList.toggle("dead", dead);
    }
    const c = { failed: 0, down: 0, degraded: 0 };
    Object.values(status).forEach((v) => { if (v in c) c[v]++; });
    $("#fail-text").textContent = failed.size
      ? `${c.failed} failed · ${c.down} down · ${c.degraded} degraded`
      : "Click any component to fail it.";
    $("#btn-restore").hidden = !failed.size;
    if (selected) fillDrawer(selected);
  }

  let failMode = false;
  function setFailMode(on) {
    failMode = on;
    $("#btn-fail").setAttribute("aria-pressed", on);
    $("#fail-bar").hidden = !on && !failed.size;
    svg.classList.toggle("failmode", on);
    root.classList.toggle("failmode", on);
  }
  function toggleFail(id) {
    failed.has(id) ? failed.delete(id) : failed.add(id);
    $("#fail-bar").hidden = !failMode && !failed.size;
    render();
  }

  // ---------- selection + drawer ----------
  let selected = null;
  const usedBy = (id) => D.nodes.filter((n) => (n.needs || []).flat().includes(id) || (n.soft || []).includes(id));

  function activate(id) {
    stopFlow();
    if (failMode) { toggleFail(id); select(id); } else select(id === selected ? null : id);
  }

  function highlight(ids, links) {
    root.classList.toggle("focus", !!ids);
    D.nodes.forEach((n) => n.g.classList.toggle("hl", !!ids && ids.has(n.id)));
    D.links.forEach((l) => l.g.classList.toggle("hl", !!links && links.has(l)));
  }

  // Focus a node: its lines and neighbours stay bright, everything else dims.
  function focusNode(id) {
    const links = new Set(D.links.filter((l) => l.a === id || l.b === id));
    const ids = new Set([id]); links.forEach((l) => { ids.add(l.a); ids.add(l.b); });
    highlight(ids, links);
  }

  function select(id) {
    selected = id;
    D.nodes.forEach((n) => n.g.classList.toggle("sel", n.id === id));
    if (!id) {
      closeDrawer(); highlight(null);
      if (location.hash) history.replaceState(null, "", location.pathname + location.search);
      return;
    }
    // In failure mode keep everything visible so the states stay readable.
    if (failMode) highlight(null);
    else focusNode(id);
    fillDrawer(id);
    clearTimeout(closeT);
    $("#drawer").classList.remove("closing");
    $("#drawer").hidden = false;
    // Phones: the card is a bottom sheet, so bring the component into the space above it
    if (innerWidth <= 720) {
      const n = byId[id], top = safeBox().y, sheet = $("#drawer").getBoundingClientRect().top;
      animateTo({ k: view.k, x: innerWidth / 2 - n.x * view.k, y: (top + sheet) / 2 - n.y * view.k });
    }
    history.replaceState(null, "", "#" + id);
  }

  let closeT;
  function closeDrawer() {
    const d = $("#drawer");
    if (d.hidden) return;
    d.classList.add("closing");
    closeT = setTimeout(() => { d.hidden = true; d.classList.remove("closing"); }, reduceMotion ? 0 : 180);
  }

  const STATE_TEXT = { ok: "Running", degraded: "Degraded", down: "Down (a dependency failed)", failed: "Failed (simulated)" };

  function fillDrawer(id) {
    const n = byId[id], st = status[id] || "ok";
    $("#d-group").textContent = (groupOf(n) || {}).label || "";
    $("#d-title").textContent = n.label;
    $("#d-sub").textContent = n.sub;
    $("#d-state").innerHTML = `<i class="dot ${st === "ok" ? "" : st}"></i>${STATE_TEXT[st]}`;

    const dl = $("#d-facts"); dl.replaceChildren();
    for (const [k, v] of Object.entries(n.facts || {})) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      dl.append(dt, dd);
    }
    const ul = $("#d-notes"); ul.replaceChildren();
    (n.notes || []).forEach((t) => { const li = document.createElement("li"); li.textContent = t; ul.append(li); });
    ul.hidden = !(n.notes || []).length;

    $("#d-if").textContent = n.onFail || "—";

    // Relations as clickable links
    const rel = $("#d-rel"); rel.replaceChildren();
    const section = (title, ids) => {
      if (!ids.length) return;
      // Plain text links separated by dots: no chips, no boxes inside the card
      const h = document.createElement("h3"); h.textContent = title;
      const p = document.createElement("p"); p.className = "links";
      ids.forEach((rid, i) => {
        if (i) { const s = document.createElement("span"); s.className = "sep"; s.textContent = " · "; p.append(s); }
        const b = document.createElement("button");
        if (["failed", "down"].includes(status[rid])) b.className = "bad";
        b.textContent = byId[rid].label;
        b.onclick = () => select(rid);
        p.append(b);
      });
      rel.append(h, p);
    };
    section("Needs", [...new Set((n.needs || []).flat())]);
    section("Nice to have", (n.soft || []).filter((x) => !(n.needs || []).flat().includes(x)));
    section("Used by", usedBy(id).map((u) => u.id));
    // What this failure alone breaks (other simulated failures ignored)
    const alone = computeStatus(new Set([id]));
    const hit = D.nodes.filter((m) => m.id !== id && alone[m.id] !== "ok").map((m) => m.id);
    section(st === "failed" ? "Breaks right now" : "Would break if it failed", hit);

    const btn = $("#d-toggle");
    btn.textContent = failed.has(id) ? `Restore ${n.label}` : `Simulate ${n.label} failing`;
    btn.classList.toggle("danger", !failed.has(id));
    btn.onclick = () => toggleFail(id);
  }

  // ---------- layers / views ----------
  const VIEWS = {
    network: ["network"], services: ["services"], storage: ["storage"],
    all: ["network", "services", "storage"],
  };
  const typeOn = Object.fromEntries(Object.keys(D.linkTypes).map((t) => [t, true]));

  let currentView = "all";
  const isShown = (l) => typeOn[l.type] && !(l.quiet && currentView === "all");
  function applyLayers() {
    D.links.forEach((l) => {
      l.g.classList.toggle("off", !typeOn[l.type]);
      l.g.classList.toggle("quiet", !!l.quiet && currentView === "all");
    });
    reroute(isShown);
    const touched = new Set();
    D.links.forEach((l) => { if (typeOn[l.type]) { touched.add(l.a); touched.add(l.b); } });
    D.nodes.forEach((n) => { n.g.style.opacity = touched.has(n.id) ? "" : "0.3"; });
    document.querySelectorAll("#legend-links button").forEach((b) => b.setAttribute("aria-pressed", typeOn[b.dataset.type]));
  }
  function setView(v) {
    currentView = v;
    document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-checked", b.dataset.view === v));
    for (const t in typeOn) typeOn[t] = VIEWS[v].includes(D.linkTypes[t].layer);
    applyLayers();
  }
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  // Legend: one toggle per link type
  for (const [t, info] of Object.entries(D.linkTypes)) {
    const b = document.createElement("button");
    b.dataset.type = t; b.setAttribute("aria-pressed", "true");
    const dash = { dns: "5 5", push: "5 5", metrics: "5 5", tunnel: "10 4" }[t] || "";
    b.innerHTML = `<svg viewBox="0 0 26 8"><line x1="1" y1="4" x2="25" y2="4" style="${linkColor(t)}" stroke-width="2.4" stroke-dasharray="${dash}"/></svg>`;
    b.append(document.createTextNode(info.label));
    b.onclick = () => {
      typeOn[t] = !typeOn[t];
      currentView = "custom";
      document.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-checked", "false"));
      applyLayers();
    };
    $("#legend-links").append(b);
  }

  // ---------- guided flows ----------
  let flow = null, flowStep = 0, packetRAF = 0;
  const packet = el("circle", { class: "packet", r: 6 }, gFx);
  packet.style.display = "none";

  function findLink(a, b) {
    return D.links.find((l) => l.a === a && l.b === b) || D.links.find((l) => l.a === b && l.b === a);
  }

  function startFlow(f) {
    select(null); setView("all");
    flow = f; flowStep = 0;
    $("#flow-title").textContent = f.title;
    $("#flow").hidden = false;
    closeMenu();
    showStep();
  }
  function stopFlow() {
    if (!flow) return;
    flow = null; cancelAnimationFrame(packetRAF);
    packet.style.display = "none";
    D.nodes.forEach((n) => n.g.classList.remove("step"));
    $("#flow").hidden = true; highlight(null);
  }

  function showStep() {
    const f = flow, a = f.path[flowStep], b = f.path[flowStep + 1];
    $("#flow-caption").textContent = f.steps[flowStep];
    $("#flow-count").textContent = `${flowStep + 1} / ${f.steps.length}`;
    $("#flow-prev").disabled = flowStep === 0;
    $("#flow-next").textContent = flowStep === f.steps.length - 1 ? "↺" : "›";

    // Whole route faintly, current hop bright
    const route = new Set(), ids = new Set(f.path);
    for (let i = 0; i < f.path.length - 1; i++) { const l = findLink(f.path[i], f.path[i + 1]); if (l) route.add(l); }
    highlight(ids, route);
    D.nodes.forEach((n) => n.g.classList.toggle("step", n.id === a || n.id === b));
    ensureVisible([byId[a], byId[b]]);

    const l = findLink(a, b);
    cancelAnimationFrame(packetRAF);
    if (!l || reduceMotion) { packet.style.display = "none"; return; }
    const len = l.path.getTotalLength(), reverse = l.a !== a, t0 = performance.now();
    packet.style.display = "";
    const tick = (now) => {
      const p = ((now - t0) % 1600) / 1600;
      const pt = l.path.getPointAtLength((reverse ? 1 - p : p) * len);
      packet.setAttribute("cx", pt.x); packet.setAttribute("cy", pt.y);
      packetRAF = requestAnimationFrame(tick);
    };
    packetRAF = requestAnimationFrame(tick);
  }

  function ensureVisible(nodes) {
    // Pan (never zoom) so both nodes of the current hop are on screen.
    const b = safeBox();
    const xs = nodes.map((n) => n.x * view.k + view.x), ys = nodes.map((n) => n.y * view.k + view.y);
    const pad = (NW / 2) * view.k + 20;
    let dx = 0, dy = 0;
    if (Math.min(...xs) - pad < b.x) dx = b.x - (Math.min(...xs) - pad);
    else if (Math.max(...xs) + pad > b.x + b.w) dx = b.x + b.w - (Math.max(...xs) + pad);
    if (Math.min(...ys) - pad < b.y) dy = b.y - (Math.min(...ys) - pad);
    else if (Math.max(...ys) + pad > b.y + b.h - 150) dy = b.y + b.h - 150 - (Math.max(...ys) + pad);
    if (dx || dy) animateTo({ k: view.k, x: view.x + dx, y: view.y + dy });
  }

  $("#flow-next").onclick = () => { flowStep = (flowStep + 1) % flow.steps.length; showStep(); };
  $("#flow-prev").onclick = () => { if (flowStep > 0) { flowStep--; showStep(); } };
  $("#flow-close").onclick = stopFlow;

  const menu = $("#flow-menu");
  for (const f of D.flows) {
    const b = document.createElement("button");
    b.setAttribute("role", "menuitem"); b.textContent = f.title;
    b.onclick = () => startFlow(f);
    menu.append(b);
  }
  function closeMenu() { menu.hidden = true; $("#btn-flows").setAttribute("aria-expanded", "false"); }
  $("#btn-flows").onclick = () => {
    const open = menu.hidden;
    menu.hidden = !open; $("#btn-flows").setAttribute("aria-expanded", open);
    if (open) menu.querySelector("button").focus();
  };
  document.addEventListener("click", (e) => { if (!e.target.closest("#flow-menu, #btn-flows")) closeMenu(); });

  // ---------- controls ----------
  $("#btn-fail").onclick = () => setFailMode(!failMode);
  $("#btn-restore").onclick = () => { failed.clear(); render(); setFailMode(failMode); };
  $("#d-close").onclick = () => select(null);
  $("#z-in").onclick = () => zoomAt(1.3, ...center(), true);
  $("#z-out").onclick = () => zoomAt(1 / 1.3, ...center(), true);
  $("#z-fit").onclick = () => fit();
  $("#repo").href = D.repo;
  $("#reviewed").textContent = `From README · reviewed ${D.reviewed}`;

  // Keyboard: nodes are focusable; global shortcuts when not typing.
  gNodes.addEventListener("keydown", (e) => {
    const node = e.target.closest(".node");
    if (node && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); activate(node.dataset.id); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (flow && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      e.preventDefault(); $(e.key === "ArrowRight" ? "#flow-next" : "#flow-prev").click(); return;
    }
    const pan = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] }[e.key];
    if (pan && (e.target === svg || e.target === document.body)) {
      e.preventDefault(); view.x += pan[0]; view.y += pan[1]; apply(); return;
    }
    if (e.key === "+" || e.key === "=") zoomAt(1.2, ...center(), true);
    else if (e.key === "-") zoomAt(1 / 1.2, ...center(), true);
    else if (e.key === "0") fit();
    else if ("1234".includes(e.key) && e.key.length === 1) setView(["network", "services", "storage", "all"][+e.key - 1]);
    else if (e.key === "f" || e.key === "F") setFailMode(!failMode);
    else if (e.key === "Escape") { closeMenu(); if (flow) stopFlow(); else if (selected) select(null); else if (failMode) setFailMode(false); }
  });

  // Hover a card (mouse): preview its lines without clicking.
  gNodes.addEventListener("pointerover", (e) => {
    const node = e.target.closest(".node");
    if (e.pointerType !== "mouse" || !node || selected || flow || failMode || pointers.size) return;
    focusNode(node.dataset.id);
  });
  gNodes.addEventListener("pointerout", (e) => {
    const node = e.target.closest(".node");
    if (e.pointerType !== "mouse" || !node || node.contains(e.relatedTarget)) return;
    if (!selected && !flow) highlight(null);
  });

  // Deep links: #caddy opens Caddy
  const fromHash = () => { const id = location.hash.slice(1); if (byId[id]) select(id); };
  window.addEventListener("hashchange", fromHash);

  let resizeT;
  window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => fit(false), 150); });

  render();
  applyLayers();
  fit(false);
  fromHash();
})();
