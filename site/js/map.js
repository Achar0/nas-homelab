// Interactive homelab map: plain SVG + vanilla JS, no build step.
(() => {
  "use strict";
  const D = window.HOMELAB;
  const NS = "http://www.w3.org/2000/svg";
  const W = 1800, H = 1100;          // world size
  const NW = 200, NH = 58;           // node card size
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
  const linkColor = (t) => `var(--l-${t})`;

  // ---------- build the SVG ----------
  const svg = $("#map");
  const defs = el("defs", {}, svg);
  const pat = el("pattern", { id: "dots", width: 28, height: 28, patternUnits: "userSpaceOnUse" }, defs);
  el("circle", { cx: 1, cy: 1, r: 1, fill: "#1b2030" }, pat);

  const root = el("g", { class: "map" }, svg);
  el("rect", { class: "bg-grid", x: -4000, y: -4000, width: W + 8000, height: H + 8000 }, root);
  const gGroups = el("g", {}, root);
  const gLinks = el("g", {}, root);
  const gNodes = el("g", {}, root);
  const gFx = el("g", {}, root);

  // Frame and column labels (labels only, no nested boxes)
  for (const g of D.groups) {
    if (!g.sub) {
      el("rect", { class: "frame", x: g.x, y: g.y, width: g.w, height: g.h, rx: 22 }, gGroups);
      el("text", { class: "frame-label", x: g.x + 24, y: g.y + 32 }, gGroups).textContent = g.label;
    } else {
      el("text", { class: "col-label", x: g.x + 10, y: g.y + 40 }, gGroups).textContent = g.label;
      if (g.id === "storage") el("line", { class: "col-rule", x1: g.x, x2: g.x + g.w, y1: g.y, y2: g.y }, gGroups);
    }
  }

  // Links. Pairs with several links get a small perpendicular offset.
  const pairCount = {};
  D.links.forEach((l) => {
    const k = [l.a, l.b].sort().join("|");
    l.idx = pairCount[k] = (pairCount[k] || 0) + 1;
  });

  function anchors(a, b) {
    // Leave from the side facing the other node.
    const dx = b.x - a.x, dy = b.y - a.y;
    if (Math.abs(dx) > NW * 0.9 || Math.abs(dy) < NH) {
      const s = Math.sign(dx) || 1;
      return [[a.x + s * NW / 2, a.y], [b.x - s * NW / 2, b.y], "h"];
    }
    const s = Math.sign(dy) || 1;
    return [[a.x, a.y + s * NH / 2], [b.x, b.y - s * NH / 2], "v"];
  }

  function linkPath(l) {
    const A = byId[l.a], B = byId[l.b];
    let [[x1, y1], [x2, y2], dir] = anchors(A, B);
    const k = [l.a, l.b].sort().join("|");
    if (pairCount[k] > 1) {
      const off = (l.idx - (pairCount[k] + 1) / 2) * 12;
      if (dir === "h") { y1 += off; y2 += off; } else { x1 += off; x2 += off; }
    }
    const c = dir === "h" ? Math.max(40, Math.abs(x2 - x1) * 0.45) : Math.max(30, Math.abs(y2 - y1) * 0.45);
    const [c1, c2] = dir === "h"
      ? [[x1 + Math.sign(x2 - x1) * c, y1], [x2 - Math.sign(x2 - x1) * c, y2]]
      : [[x1, y1 + Math.sign(y2 - y1) * c], [x2, y2 - Math.sign(y2 - y1) * c]];
    return `M${x1},${y1} C${c1} ${c2} ${x2},${y2}`;
  }

  for (const l of D.links) {
    const g = el("g", { class: "lg" + (l.quiet ? " quiet" : ""), "data-type": l.type }, gLinks);
    const d = linkPath(l);
    l.path = el("path", { class: "link", d, stroke: linkColor(l.type) }, g);
    if (!reduceMotion) el("path", { class: "link-flow", d, stroke: linkColor(l.type) }, g);
    if (l.label) {
      const len = l.path.getTotalLength();
      const p = l.path.getPointAtLength(len / 2);
      el("text", { class: "link-label", x: p.x, y: p.y - 5, "text-anchor": "middle" }, g).textContent = l.label;
    }
    l.g = g;
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

  function select(id) {
    selected = id;
    D.nodes.forEach((n) => n.g.classList.toggle("sel", n.id === id));
    if (!id) {
      $("#drawer").hidden = true; highlight(null);
      if (location.hash) history.replaceState(null, "", location.pathname + location.search);
      return;
    }
    // In failure mode keep everything visible so the states stay readable.
    if (failMode) highlight(null);
    else {
      const links = new Set(D.links.filter((l) => l.a === id || l.b === id));
      const ids = new Set([id]); links.forEach((l) => { ids.add(l.a); ids.add(l.b); });
      highlight(ids, links);
    }
    fillDrawer(id);
    $("#drawer").hidden = false;
    history.replaceState(null, "", "#" + id);
  }

  const STATE_TEXT = { ok: "Running", degraded: "Degraded", down: "Down (a dependency failed)", failed: "Failed (simulated)" };

  function fillDrawer(id) {
    const n = byId[id], st = status[id] || "ok";
    $("#d-title").textContent = n.label;
    $("#d-sub").textContent = n.sub;
    $("#d-state").innerHTML = `<i class="led ${st === "ok" ? "" : st}"></i>${STATE_TEXT[st]}`;

    const dl = $("#d-facts"); dl.replaceChildren();
    for (const [k, v] of Object.entries(n.facts || {})) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      dl.append(dt, dd);
    }
    const ul = $("#d-notes"); ul.replaceChildren();
    (n.notes || []).forEach((t) => { const li = document.createElement("li"); li.textContent = t; ul.append(li); });
    ul.hidden = !(n.notes || []).length;

    $("#d-if").innerHTML = "";
    const strong = document.createElement("strong"); strong.textContent = "If it fails";
    $("#d-if").append(strong, document.createTextNode(n.onFail || "—"));

    // Relations as clickable chips
    const rel = $("#d-rel"); rel.replaceChildren();
    const section = (title, ids) => {
      if (!ids.length) return;
      const h = document.createElement("h3"); h.textContent = title; rel.append(h);
      ids.forEach((rid) => {
        const b = document.createElement("button");
        b.className = "chip" + (["failed", "down"].includes(status[rid]) ? " bad" : "");
        b.textContent = byId[rid].label;
        b.onclick = () => select(rid);
        rel.append(b);
      });
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

  function applyLayers() {
    D.links.forEach((l) => l.g.classList.toggle("off", !typeOn[l.type]));
    const touched = new Set();
    D.links.forEach((l) => { if (typeOn[l.type]) { touched.add(l.a); touched.add(l.b); } });
    D.nodes.forEach((n) => { n.g.style.opacity = touched.has(n.id) ? "" : "0.3"; });
    document.querySelectorAll("#legend-links button").forEach((b) => b.setAttribute("aria-pressed", typeOn[b.dataset.type]));
  }
  function setView(v) {
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
    b.innerHTML = `<svg viewBox="0 0 26 8"><line x1="1" y1="4" x2="25" y2="4" stroke="${linkColor(t)}" stroke-width="2.4" stroke-dasharray="${dash}"/></svg>`;
    b.append(document.createTextNode(info.label));
    b.onclick = () => {
      typeOn[t] = !typeOn[t];
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
