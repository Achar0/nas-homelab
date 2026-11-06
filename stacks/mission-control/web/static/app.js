// Mission Control page: state, data fetching, rendering.
// State lives in the URL hash (#cpu/24H, #card=qbittorrent/24H) so a reload keeps the view.
import { RANGES, rateWindow, summarize, toSeries, formatTemp, formatPercent, autoRefresh } from "./lib.js";
import { METRICS, DOCK } from "./metrics.js";

const $ = (id) => document.getElementById(id);
const LIVE_MS = 15000;
const SPARK_MS = 60000;
const state = { metric: "cpu", range: "24H", open: null };

// ---------- data ----------
async function api(path, params) {
  const r = await fetch(`${path}?${new URLSearchParams(params)}`);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  const j = await r.json();
  if (j.status && j.status !== "success") throw new Error(j.error || "query failed");
  return j.data ?? j;
}

const expand = (expr, step) => expr.replaceAll("$w", rateWindow(step));

// One instant value per expression (first series), or null
export async function instant(expr) {
  const d = await api("/api/prom/query", { query: expand(expr, 15) });
  const v = d.result?.[0]?.value?.[1];
  return v === undefined ? null : Number(v);
}

export async function instantAll(expr) {
  const d = await api("/api/prom/query", { query: expand(expr, 15) });
  return d.result || [];
}

// Several expressions over a range -> {x, ys} on one shared time grid
export async function rangeSeries(queries, range) {
  const { seconds, step } = RANGES[range];
  const end = Math.floor(Date.now() / 1000 / step) * step;
  const start = end - seconds;
  const results = await Promise.all(queries.map((q) =>
    api("/api/prom/query_range", { query: expand(q.expr, step), start, end, step })
      .then((d) => d.result?.[0] ?? { values: [] })
      .catch(() => ({ values: [] }))));
  return toSeries(results, start, end, step);
}

// ---------- big chart (shared by the main flow and expanded cards) ----------
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function timeLabel(t, range) {
  const d = new Date(t * 1000);
  const hm = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (range === "1H" || range === "24H") return hm;
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return range === "1Y" ? day : `${day} ${hm}`;
}

/**
 * Big area chart that fills `el`. onHover(i | null) is called as the pointer moves,
 * so the caller writes the readout into its own header (never a floating tooltip).
 */
export function makeChart(el, series, format, onHover, { max = null, range = () => "24H", integer = false } = {}) {
  const fill = (color) => (u) => {
    const g = u.ctx.createLinearGradient(0, u.bbox.top, 0, u.bbox.top + u.bbox.height);
    g.addColorStop(0, color + (series.length > 1 ? "33" : "66"));
    g.addColorStop(1, color + "00");
    return g;
  };
  const axis = {
    stroke: css("--text-2"),
    grid: { stroke: css("--hairline"), width: 1 },
    ticks: { show: false },
    font: `12px ${getComputedStyle(document.body).fontFamily}`,
  };
  const opts = {
    width: el.clientWidth || 600,
    height: el.clientHeight || 300,
    padding: [series.length > 1 ? 30 : 10, 22, 0, 0],
    legend: { show: false },
    cursor: { y: false, points: { size: 8, width: 2 }, drag: { x: false, y: false } },
    scales: {
      x: { time: true },
      y: { range: (u, lo, hi) => [Math.min(0, lo ?? 0), Math.min(max ?? Infinity, ((hi ?? 0) * 1.15) || 1)] },
    },
    axes: [
      { ...axis, space: 90, values: (u, ticks) => ticks.map((t) => timeLabel(t, range())) },
      { ...axis, size: 70, space: 56, values: (u, ticks) => ticks.map((v) => format(v)),
        ...(integer ? { incrs: [1, 2, 5, 10, 20, 50, 100, 200, 500, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6] } : {}) },
    ],
    series: [{}, ...series.map((s) => ({
      label: s.name, stroke: s.color, width: 2, fill: series.length > 1 ? undefined : fill(s.color), spanGaps: false,
      points: { show: false },
    }))],
    hooks: { setCursor: [(u) => onHover(u.cursor.idx ?? null)] },
  };
  const plot = new uPlot(opts, [[], ...series.map(() => [])], el);
  el.addEventListener("mouseleave", () => onHover(null));
  // Keep the chart exactly the size of its cell (checked on resize and on every data update,
  // because the cell can change size before the observer reports it)
  const fit = () => {
    const w = el.clientWidth, h = el.clientHeight;
    if (w && h && (w !== plot.width || h !== plot.height)) plot.setSize({ width: w, height: h });
  };
  const ro = new ResizeObserver(fit);
  ro.observe(el);
  addEventListener("resize", fit);
  return {
    set: (x, ys) => { plot.setData([x, ...ys]); requestAnimationFrame(fit); },
    destroy: () => { ro.disconnect(); removeEventListener("resize", fit); plot.destroy(); },
  };
}

// Small 24 h sparkline as inline SVG
function sparkline(values, color) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && Number.isFinite(v));
  if (pts.length < 2) return "";
  const ys = pts.map(([, v]) => v);
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1, n = values.length - 1 || 1;
  const d = pts.map(([i, v]) => `${((i / n) * 100).toFixed(2)},${(22 - ((v - lo) / span) * 20).toFixed(2)}`).join(" ");
  return `<svg viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">
    <polyline fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" points="${d}"/></svg>`;
}

// ---------- main flow ----------
let chart = null, chartFor = "", current = null;

const metricById = (id) => METRICS.find((m) => m.id === id) || METRICS[0];
export const rangeName = { "1H": "last hour", "24H": "last 24 h", "1W": "last week", "1M": "last month", "1Y": "last year" };

export function renderRanges(el, active, onPick) {
  el.innerHTML = Object.keys(RANGES).map((r) =>
    `<button role="tab" aria-selected="${r === active}" data-r="${r}">${r}</button>`).join("");
  el.onclick = (e) => { const b = e.target.closest("button"); if (b) onPick(b.dataset.r); };
}

function seriesOf(m) {
  return m.queries.map((q) => ({ name: q.name, color: q.color || m.color }));
}

export function summaryLine(m, data, range) {
  const s = summarize(data.ys[0]);
  if (s.last === null) return "No data for this range yet";
  const when = timeLabel(data.x[s.peakIndex], range);
  return `avg <b>${m.format(s.avg)}</b> · peak <b>${m.format(s.peak)}</b> at ${when}`;
}

export function hoverLine(series, format, data, i, range) {
  const parts = series.map((s, k) => {
    const v = data.ys[k][i];
    return series.length > 1 ? `${s.name} <b>${format(v)}</b>` : `<b>${format(v)}</b>`;
  });
  return `${timeLabel(data.x[i], range)} · ${parts.join(" · ")}`;
}

export function legendHtml(series) {
  return series.length > 1
    ? series.map((s) => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("")
    : "";
}

async function renderFlow() {
  const m = metricById(state.metric), range = state.range;
  $("eyebrow").textContent = `${m.label} · ${rangeName[range]}`;
  renderRanges($("ranges"), range, (r) => go({ range: r }));
  document.querySelectorAll(".tiles .tile").forEach((t) => t.setAttribute("aria-pressed", t.dataset.id === m.id));
  const series = seriesOf(m);
  const key = `${m.id}`;
  if (chartFor !== key) {
    chart?.destroy();
    $("chart").querySelectorAll(".uplot").forEach((n) => n.remove());
    chart = makeChart($("chart"), series, m.format, (i) => {
      if (!current) return;
      $("context").innerHTML = i === null ? summaryLine(m, current, state.range) : hoverLine(series, m.format, current, i, state.range);
    }, { max: m.max ?? null, range: () => state.range });
    chartFor = key;
  }
  $("legend").innerHTML = legendHtml(series);
  $("chart").classList.add("fading");
  try {
    const data = await rangeSeries(m.queries, range);
    if (m.id !== state.metric || range !== state.range) return; // user moved on
    current = data;
    chart.set(data.x, data.ys);
    $("context").innerHTML = summaryLine(m, data, range);
    $("chart").querySelector(".empty")?.remove();
  } catch {
    $("context").textContent = "Prometheus is not answering right now";
  } finally {
    $("chart").classList.remove("fading");
  }
}

function buildTiles() {
  $("tiles").innerHTML = METRICS.map((m) => `
    <button class="tile" data-id="${m.id}" style="--c:${m.color}" aria-pressed="false">
      <span class="k">${m.label}</span><span class="v" id="tv-${m.id}">—</span><span id="ts-${m.id}"></span>
    </button>`).join("");
  $("tiles").onclick = (e) => { const t = e.target.closest(".tile"); if (t) go({ metric: t.dataset.id, open: null }); };
}

async function refreshLive() {
  await Promise.all(METRICS.map(async (m) => {
    const v = await instant(m.queries[0].expr).catch(() => null);
    $(`tv-${m.id}`).textContent = m.format(v);
    if (m.id === state.metric && !state.open) $("hero").textContent = m.format(v);
  }));
}

async function refreshSparks() {
  await Promise.all(METRICS.map(async (m) => {
    const d = await rangeSeries([m.queries[0]], "24H").catch(() => null);
    if (d) $(`ts-${m.id}`).innerHTML = sparkline(d.ys[0], m.color);
  }));
}

// ---------- disks ----------
const DISKS = [
  { id: "md1", name: "RAID 1", kind: "raid" },
  { id: "sda", name: "Disk 1", kind: "smart" },
  { id: "sdb", name: "Disk 2", kind: "smart" },
  { id: "nvme0", name: "NVMe", kind: "smart" },
];
let diskInfo = {};

function byDevice(results) {
  const out = {};
  for (const r of results) out[r.metric.device] = Number(r.value[1]);
  return out;
}

async function refreshDisks() {
  const q = (e) => instantAll(e).catch(() => []);
  const [active, required, status, temp, hours, attrs, used] = await Promise.all([
    q('node_md_disks{state="active"}'), q("node_md_disks_required"), q("smartctl_device_smart_status"),
    q('smartctl_device_temperature{temperature_type="current"}'), q("smartctl_device_power_on_seconds"),
    q('smartctl_device_attribute{attribute_name=~"Reallocated_Sector_Ct|Current_Pending_Sector",attribute_value_type="raw"}'),
    q("smartctl_device_percentage_used"),
  ]);
  const A = byDevice(active), R = byDevice(required), S = byDevice(status), T = byDevice(temp), H = byDevice(hours), U = byDevice(used);
  const sectors = {};
  for (const r of attrs) sectors[r.metric.device] = (sectors[r.metric.device] || 0) + Number(r.value[1]);

  diskInfo = {};
  for (const d of DISKS) {
    if (d.kind === "raid") {
      const a = A[d.id], req = R[d.id];
      const level = a === undefined ? "" : a < req ? "bad" : "ok";
      diskInfo[d.id] = { level, line: a === undefined ? "—" : a < req ? "Degraded" : "Healthy",
        rows: [["Drives active", a === undefined ? "—" : `${a} of ${req}`], ["Mirror", "Disk 1 + Disk 2"]] };
      continue;
    }
    const t = T[d.id], st = S[d.id], sec = sectors[d.id] || 0, u = U[d.id];
    let level = st === undefined ? "" : "ok";
    if (sec > 0 || (u ?? 0) > 80 || (t ?? 0) > 50) level = "warn";
    if (st === 0) level = "bad";
    const rows = [["SMART", st === undefined ? "—" : st ? "Passed" : "Failing"],
      ["Temperature", formatTemp(t)],
      ["Powered on", H[d.id] ? `${Math.round(H[d.id] / 3600).toLocaleString("en-US")} h` : "—"]];
    if (d.id === "nvme0") rows.push(["Wear", formatPercent(u)]);
    else rows.push(["Bad sectors", String(sec)]);
    diskInfo[d.id] = { level, line: formatTemp(t), rows };
  }
  $("disks").innerHTML = DISKS.map((d) => {
    const i = diskInfo[d.id];
    return `<button class="disk" data-id="${d.id}" aria-haspopup="dialog">
      <span class="dot ${i.level}"></span><span class="n">${d.name}</span><span class="t">${i.line}</span></button>`;
  }).join("");
  dispatchEvent(new Event("resize"));   // the disks row may have changed the chart's room
}

function showDisk(btn) {
  const d = DISKS.find((x) => x.id === btn.dataset.id), i = diskInfo[d.id], p = $("popover");
  p.innerHTML = `<h3>${d.name}</h3><dl>${i.rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  p.hidden = false;
  const r = btn.getBoundingClientRect(), h = p.offsetHeight;
  p.style.left = `${Math.min(r.left, innerWidth - p.offsetWidth - 12)}px`;
  p.style.top = `${r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8}px`;
}

$("disks").addEventListener("click", (e) => { const b = e.target.closest(".disk"); if (b) showDisk(b); });
$("disks").addEventListener("mouseover", (e) => { const b = e.target.closest(".disk"); if (b && matchMedia("(hover: hover)").matches) showDisk(b); });
$("disks").addEventListener("mouseleave", () => { $("popover").hidden = true; });
document.addEventListener("click", (e) => { if (!e.target.closest(".disk")) $("popover").hidden = true; });

// ---------- navigation ----------
function readHash() {
  const h = location.hash.slice(1);
  const [a, b] = h.split("/");
  if (a?.startsWith("card=")) { state.open = a.slice(5); state.range = RANGES[b] ? b : state.range; return; }
  state.open = null;
  if (METRICS.some((m) => m.id === a)) state.metric = a;
  if (RANGES[b]) state.range = b;
}

function writeHash() {
  const h = state.open ? `#card=${state.open}/${state.range}` : `#${state.metric}/${state.range}`;
  if (location.hash !== h) history.replaceState(null, "", h);
}

export const hooks = { renderPanel: null, closePanel: null };   // set by cards.js

export function go(change) {
  Object.assign(state, change);
  writeHash();
  render();
}

export function render() {
  if (state.open && hooks.renderPanel) return hooks.renderPanel(state);
  hooks.closePanel?.();
  renderFlow();
}

export { state };

// ---------- dock ----------
function buildDock() {
  $("dock").innerHTML = DOCK.map((a) => `
    <a class="dock-app" href="${a.href}" target="_blank" rel="noopener" title="${a.name}">
      ${a.mono ? `<span class="dock-icon mono" style="--icon:url('icons/${a.icon}')"></span>`
               : `<span class="dock-icon"><img src="icons/${a.icon}" alt=""></span>`}
      <span class="dock-label">${a.name}</span>
    </a>`).join("");
}

// ---------- start ----------
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.open) go({ open: null }); });
readHash();
buildDock();
buildTiles();
render();
refreshLive(); refreshSparks(); refreshDisks();
setInterval(() => { if (!document.hidden) { refreshLive(); refreshDisks(); } }, LIVE_MS);
setInterval(() => { if (!document.hidden) { refreshSparks(); if (!state.open && autoRefresh(state.range)) renderFlow(); } }, SPARK_MS);
window.addEventListener("hashchange", () => { readHash(); render(); });
