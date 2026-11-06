// Rail of service cards + the expanded card panel that covers the main flow.
// One card open at a time; click the same card, ✕ or Esc to close; another card swaps in place.
import { CARDS } from "./metrics.js";
import {
  makeChart, rangeSeries, instant, instantAll, go, render, state, hooks,
  renderRanges, rangeName, summaryLine, hoverLine, legendHtml,
} from "./app.js";
import { formatAgo, unavailable, formatCount, esc, autoRefresh } from "./lib.js";
import { connections } from "./connections.js";

const $ = (id) => document.getElementById(id);
const rail = $("rail"), panel = $("panel"), flow = $("flow");
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
// ?static (used for headless screenshots, where animations never advance): no animations at all
const STATIC = new URLSearchParams(location.search).has("static");
if (STATIC) document.documentElement.classList.add("static");
const EASE = "cubic-bezier(0.2, 0.9, 0.25, 1)";
export const extraCards = [connections];   // non-Prometheus cards: {id, railHtml, refresh, open(panel), close}

// ---------- rail ----------
function buildRail() {
  rail.innerHTML = `<h2>Services</h2>` + CARDS.map((c) => `
    <button class="card" data-id="${c.id}" aria-expanded="false" aria-controls="panel">
      <span class="t"><span>${c.title}</span><span class="chev" aria-hidden="true">›</span></span>
      <span class="v" id="cv-${c.id}">—</span>
      <span class="s" id="cs-${c.id}">&nbsp;</span>
    </button>`).join("") + extraCards.map((x) => x.railHtml).join("");
  rail.onclick = (e) => {
    const b = e.target.closest(".card");
    if (b) go({ open: state.open === b.dataset.id ? null : b.dataset.id });
  };
}

async function refreshCard(c) {
  const [up, v, sub] = await Promise.all([
    instant(`mc_up{source="${c.source}"}`).catch(() => null),
    instant(c.key.expr).catch(() => null),
    c.sub.expr ? instant(c.sub.expr).catch(() => null) : Promise.resolve(null),
  ]);
  const off = unavailable(up, v);
  const card = rail.querySelector(`[data-id="${c.id}"]`);
  card.classList.toggle("off", off);
  $(`cv-${c.id}`).textContent = off ? "—" : c.key.format(v);
  $(`cs-${c.id}`).textContent = off ? "unavailable" : c.sub.ago ? c.sub.text(formatAgo(sub)) : c.sub.text(sub);
}

function refreshRail() {
  CARDS.forEach((c) => refreshCard(c));
  extraCards.forEach((x) => x.refresh?.());
}

// ---------- expand / collapse (grows out of the card, shrinks back into it) ----------
let anim = null;

function cardRect(id) {
  return rail.querySelector(`[data-id="${id}"]`)?.getBoundingClientRect();
}

function transformFrom(rect) {
  const p = panel.getBoundingClientRect();
  return `translate(${rect.left - p.left}px, ${rect.top - p.top}px) scale(${rect.width / p.width}, ${rect.height / p.height})`;
}

function grow(id) {
  if (STATIC) return;
  const rect = cardRect(id);
  anim?.cancel();
  panel.style.transformOrigin = "0 0";
  if (reduceMotion.matches || !rect) {
    anim = panel.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 150 });
    return;
  }
  anim = panel.animate([{ transform: transformFrom(rect), opacity: 0.4 }, { transform: "none", opacity: 1 }],
    { duration: 320, easing: EASE });
  // content fades in once the surface has mostly arrived, so text never looks squashed
  [...panel.children].forEach((el) => el.animate([{ opacity: 0 }, { opacity: 0 }, { opacity: 1 }],
    { duration: 320, easing: "ease-out" }));
}

function shrink(id, done) {
  if (STATIC) return done();
  const rect = cardRect(id);
  const start = getComputedStyle(panel).transform;   // start from where it is now (interruptible)
  anim?.cancel();
  if (reduceMotion.matches || !rect) {
    anim = panel.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 150 });
  } else {
    anim = panel.animate([{ transform: start === "none" ? "none" : start, opacity: 1 },
      { transform: transformFrom(rect), opacity: 0 }], { duration: 260, easing: EASE });
  }
  anim.onfinish = done;
}

// ---------- panel ----------
let openId = null, chart = null, current = null, active = null;

function setRailState(id) {
  rail.querySelectorAll(".card").forEach((b) => b.setAttribute("aria-expanded", String(b.dataset.id === id)));
  flow.classList.toggle("dimmed", Boolean(id));
  flow.inert = Boolean(id);
}

function panelHtml(c) {
  return `
    <header class="head">
      <div class="head-text">
        <p class="eyebrow" id="p-eyebrow">${c.title}</p>
        <p class="hero" id="p-hero">—</p>
        <p class="context" id="p-context">&nbsp;</p>
      </div>
      <div class="head-right">
        <div class="segmented" role="tablist" aria-label="Time range" id="p-ranges"></div>
        ${c.href ? `<a class="open" href="${c.href}" target="_blank" rel="noopener">Open ${c.title} ↗</a>` : ""}
        <button class="close" id="p-close" aria-label="Close">✕</button>
      </div>
    </header>
    <div class="chart" id="p-chart"><div class="legend" id="p-legend"></div></div>
    ${c.devices ? `<div class="devices" id="p-devices"></div>` : ""}
    <div class="tiles" id="p-tiles" style="grid-template-columns: repeat(${c.tiles.length}, minmax(0, 1fr))">
      ${c.tiles.map((t, i) => `<div class="tile"><span class="k">${t.label}</span><span class="v" id="pt-${i}">—</span></div>`).join("")}
    </div>`;
}

async function fillPanel(c, range) {
  $("p-eyebrow").textContent = `${c.title} · ${rangeName[range]}${c.chartNote ? ` · ${c.chartNote}` : ""}`;
  renderRanges($("p-ranges"), range, (r) => go({ range: r }));
  const fmt = { format: c.chartFormat };
  const [v, data] = await Promise.all([
    instant(c.key.expr).catch(() => null),
    rangeSeries(c.chart, range).catch(() => null),
  ]);
  if (openId !== c.id || state.range !== range) return;
  $("p-hero").textContent = v === null ? "—" : c.key.format(v);
  if (data) {
    current = data;
    chart.set(data.x, data.ys);
    $("p-context").innerHTML = summaryLine(fmt, data, range);
  }
  c.tiles.forEach(async (t, i) => {
    if (t.labelOf) {
      const r = await instantAll(t.expr).catch(() => []);
      $(`pt-${i}`).textContent = r[0]?.metric?.[t.labelOf] ?? "—";
      $(`pt-${i}`).title = $(`pt-${i}`).textContent;
    } else {
      $(`pt-${i}`).textContent = t.format(await instant(t.expr).catch(() => null));
    }
  });
  if (c.devices) fillDevices();
}

async function fillDevices() {
  const [online, seen] = await Promise.all([
    instantAll("mc_tailscale_peer_online").catch(() => []),
    instantAll("mc_tailscale_peer_last_seen_seconds").catch(() => []),
  ]);
  const last = Object.fromEntries(seen.map((r) => [r.metric.name, Number(r.value[1])]));
  $("p-devices").innerHTML = online
    .sort((a, b) => Number(b.value[1]) - Number(a.value[1]) || a.metric.name.localeCompare(b.metric.name))
    .map((r) => {
      const on = r.value[1] === "1";
      return `<div class="device"><span class="dot ${on ? "ok" : ""}"></span><span>${esc(r.metric.name)}</span>
        <span class="t">${on ? "online" : formatAgo(last[r.metric.name])}</span></div>`;
    }).join("") || `<div class="device">No devices</div>`;
  dispatchEvent(new Event("resize"));   // the device list may have taken room from the chart
}

function openCard(c, range) {
  const swapping = openId !== null && openId !== c.id;
  const fresh = openId !== c.id;
  if (fresh) {
    active?.close?.();
    active = null;
    chart?.destroy();
    panel.className = "panel";
    panel.innerHTML = panelHtml(c);
    $("p-close").onclick = () => go({ open: null });
    const series = c.chart.map((s) => ({ name: s.name, color: s.color }));
    $("p-legend").innerHTML = legendHtml(series);
    panel.hidden = false;
    chart = makeChart($("p-chart"), series, c.chartFormat, (i) => {
      if (!current) return;
      $("p-context").innerHTML = i === null ? summaryLine({ format: c.chartFormat }, current, state.range)
        : hoverLine(series, c.chartFormat, current, i, state.range);
    }, { range: () => state.range, integer: c.chartFormat === formatCount });
    if (!swapping) grow(c.id);
    openId = c.id;
    current = null;
  }
  setRailState(c.id);
  fillPanel(c, range);
}

function openExtra(x) {
  if (openId !== x.id) {
    active?.close?.();
    chart?.destroy();
    chart = null;
    const swapping = openId !== null;
    panel.hidden = false;
    x.open(panel);
    if (!swapping) grow(x.id);
    openId = x.id;
    active = x;
  }
  setRailState(x.id);
}

function closePanel() {
  if (openId === null) return;
  const id = openId;
  openId = null;
  setRailState(null);
  shrink(id, () => {
    if (openId !== null) return;   // reopened while shrinking
    active?.close?.();
    active = null;
    chart?.destroy();
    chart = null;
    panel.hidden = true;
    panel.innerHTML = "";
  });
}

function renderPanel(s) {
  const c = CARDS.find((x) => x.id === s.open);
  const x = extraCards.find((e) => e.id === s.open);
  if (c) openCard(c, s.range);
  else if (x) openExtra(x);
  else go({ open: null });
}

// ---------- start ----------
export function startCards() {
  buildRail();
  hooks.renderPanel = renderPanel;
  hooks.closePanel = closePanel;
  refreshRail();
  setInterval(() => {
    if (document.hidden) return;
    refreshRail();
    const c = CARDS.find((x) => x.id === openId);
    if (c && autoRefresh(state.range)) fillPanel(c, state.range);
  }, 15000);
  if (state.open) render();
}

startCards();

