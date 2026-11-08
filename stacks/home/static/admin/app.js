// Home page: attention (+ urgent takeover), news carousel, arrivals, compact Mission Control, dock.
import { esc, formatAgo, greeting, fmtTB, fmtMbps, applyLayout } from "../lib.js";
import { mountNews } from "../news.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
if (params.has("static")) document.documentElement.classList.add("static");   // headless screenshots
const DEMO = ["urgent", "many"].includes(params.get("demo")) ? `?demo=${params.get("demo")}` : "";
const host = location.hostname;
const at = (port, scheme = "http") => `${scheme}://${host}:${port}`;

const APPS = {
  netwatch: { name: "Netwatch", href: at(8790) },
  kuma: { name: "Uptime Kuma", href: at(3002) },
  mission: { name: "Mission Control", href: at(8800) },
  speedtest: { name: "Speedtest", href: at(8765) },
  dockge: { name: "Dockge", href: at(5001) },
  qbittorrent: { name: "qBittorrent", href: at(8888) },
};

const DOCK = [
  { name: "Mission Control", icon: "mdi-monitor-dashboard.svg", mono: true, href: at(8800) },
  { name: "AdGuard", icon: "adguard-home.svg", href: at(8080) },
  { name: "qBittorrent", icon: "qbittorrent.svg", href: at(8888) },
  { name: "AutoBangumi", icon: "mdi-television-classic.svg", mono: true, href: at(7892) },
  { name: "Speedtest", icon: "speedtest-tracker.svg", href: at(8765) },
  { name: "Uptime Kuma", icon: "uptime-kuma.svg", href: at(3002) },
  { name: "Dockge", icon: "dockge.svg", href: at(5001) },
  { name: "Netwatch", icon: "mdi-earth.svg", mono: true, href: at(8790) },
  { name: "Glances", icon: "glances.svg", href: at(61208) },
  { name: "UGOS", icon: "mdi-nas.svg", mono: true, href: at(9443, "https") },
];

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) location.reload();   // session ended: the reload lands on the login
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

// ---------- header ----------
function renderHello() {
  const d = new Date();
  $("hello").textContent = greeting(d.getHours());
  $("today").textContent = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }) +
    " · " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

// ---------- attention: one card per alert, highest priority first ----------
let ackedLocally = new Set();
const LABEL = (it) => it.resolved ? "Resolved" : it.level === "urgent" ? (it.acked ? "Urgent · acknowledged" : "Urgent") : "Warning";

function attCard(it) {
  const app = APPS[it.app];
  const cls = it.resolved ? "resolved" : it.level === "urgent" ? (it.acked ? "urgent acked" : "urgent") : "normal";
  return `<article class="att ${cls}">
    <header><span class="lvl">${LABEL(it)}</span><span class="when">${esc(it.resolved ? "" : formatAgo(it.since))}</span>
      <button class="x" data-id="${esc(it.id)}" aria-label="Dismiss">✕</button></header>
    <b>${esc(it.title)}</b>
    <p>${esc(it.detail)}</p>
    ${app ? `<a href="${app.href}" target="_blank" rel="noopener">Open ${esc(app.name)} ↗</a>` : ""}
  </article>`;
}

async function refreshAttention() {
  let data;
  try { data = await getJSON("/api/attention" + DEMO); } catch { return; }
  const items = (data.items || []).map((i) => (ackedLocally.has(i.id) ? { ...i, acked: true } : i));
  const el = $("attention");
  el.classList.toggle("single", items.length === 1);
  el.innerHTML = items.length ? items.map(attCard).join("")
    : `<p class="quiet"><span class="dot"></span>All quiet on the NAS</p>`;
  document.querySelector("#takeover .t-note").hidden = data.push === false;   // only say it if it's true
  showTakeover(data.urgent);
}

$("attention").addEventListener("click", async (e) => {
  const b = e.target.closest("button.x");
  if (!b) return;
  b.closest(".att").remove();
  if (!b.dataset.id.startsWith("demo")) await fetch(`/api/attention/${encodeURIComponent(b.dataset.id)}/dismiss`, { method: "POST" }).catch(() => {});
  refreshAttention();
});

// ---------- takeover ----------
let takeoverId = null;
function showTakeover(urgent) {
  const t = $("takeover");
  if (!urgent || ackedLocally.has(urgent.id)) { t.hidden = true; takeoverId = null; return; }
  if (takeoverId === urgent.id) return;
  takeoverId = urgent.id;
  $("t-title").textContent = urgent.title;
  $("t-detail").textContent = urgent.detail;
  const app = APPS[urgent.app];
  $("t-open").hidden = !app;
  if (app) { $("t-open").href = app.href; $("t-open").textContent = `Open ${app.name}`; }
  t.hidden = false;
  $("t-ack").focus();
}
$("t-ack").addEventListener("click", async () => {
  const id = takeoverId;
  ackedLocally.add(id);
  $("takeover").hidden = true;
  takeoverId = null;
  if (!id.startsWith("demo")) await fetch(`/api/attention/${encodeURIComponent(id)}/ack`, { method: "POST" }).catch(() => {});
  refreshAttention();   // it stays as a red banner card while the problem lasts
});
// keep focus inside the takeover while it's open
document.addEventListener("keydown", (e) => {
  if ($("takeover").hidden || e.key !== "Tab") return;
  const f = [...$("takeover").querySelectorAll("a:not([hidden]), button")];
  const i = f.indexOf(document.activeElement);
  e.preventDefault();
  f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
});

// ---------- news ----------
const news = mountNews({
  getJSON,
  topics: { all: "All", tech: "Tech", markets: "Markets", discoveries: "Discoveries", opened: "Opened" },
  // remember which stories you actually opened (kept on the NAS, see /api/news?topic=opened)
  onOpen: (id) => navigator.sendBeacon(`/api/news/${encodeURIComponent(id)}/open`),
  keysBlocked: () => !$("takeover").hidden,
});

// ---------- arrivals ----------
async function refreshArrivals() {
  let data;
  try { data = await getJSON("/api/arrivals"); } catch { return; }
  const label = (x) => esc(x.ep ? `${x.show} · ${x.ep}` : x.show);
  const done = (data.arrived || []).map((a) => `<div class="ep"><b>${label(a)}</b><span>${esc(formatAgo(a.at))}</span></div>`);
  const dl = (data.downloading || []).map((d) => `<div class="ep ${d.stalled ? "stalled" : ""}"><b>${label(d)}</b>
    <span>${d.stalled ? "stalled" : d.eta ? `${Math.ceil(d.eta / 60)} min left` : "downloading"} · ${Math.floor(d.progress * 100)}%</span>
    <div class="bar"><i style="width:${(d.progress * 100).toFixed(1)}%"></i></div></div>`);
  $("eps").innerHTML = [...done, ...dl].join("") || `<div class="ep none">No new episodes in the last 48 h</div>`;
}

// ---------- rail: compact Mission Control ----------
const fmtPct = (v) => (v === null ? "—" : `${v < 10 ? v.toFixed(1) : Math.round(v)}%`);
const fmtBytes = (v) => {
  if (v === null) return "—";
  const u = ["B/s", "KB/s", "MB/s", "GB/s"]; let i = 0;
  while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
};

const RAIL_DEFAULT = [
  { id: "cpu", k: "CPU", q: '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])))', f: fmtPct, mc: "#cpu/24H" },
  { id: "memory", k: "Memory", q: "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)", f: fmtPct, mc: "#mem/24H" },
  { id: "temperature", k: "Temperature", q: 'node_hwmon_temp_celsius{chip=~".*coretemp.*",sensor="temp1"}', f: (v) => (v === null ? "—" : `${Math.round(v)}°C`), mc: "#temps/24H" },
  { id: "free", k: "Free space", q: 'node_filesystem_avail_bytes{mountpoint="/volume1"}', f: fmtTB, mc: "" },
];
const SERVICES_DEFAULT = [
  { id: "qbittorrent", k: "qBittorrent", s: "upload", q: "mc_qbt_upload_bytes_per_second", f: fmtBytes, mc: "#card=qbittorrent/24H" },
  { id: "adguard", k: "AdGuard", s: "blocked · 24 h", q: "100 * mc_adguard_blocked_24h / mc_adguard_queries_24h", f: fmtPct, mc: "#card=adguard/24H" },
  { id: "speedtest", k: "Speedtest", s: "last download", q: "mc_speedtest_download_bits_per_second", f: fmtMbps, mc: "#card=speedtest/24H" },
];

let RAIL = RAIL_DEFAULT, SERVICES = SERVICES_DEFAULT;

function buildRail() {
  const tile = (x, i, grp) => `<a class="tile" href="${at(8800)}/${x.mc}" target="_blank" rel="noopener">
    <span class="k">${x.k}</span><span class="v" id="r-${grp}${i}">—</span>${x.s ? `<span class="s">${x.s}</span>` : ""}</a>`;
  $("rail").innerHTML = `<h2>NAS</h2><div class="grid2">${RAIL.map((x, i) => tile(x, i, "a")).join("")}</div>` +
    SERVICES.map((x, i) => tile(x, i, "b")).join("") +   // Mission Control itself is in the dock
    `<div class="tile"><span class="k">IPTV</span><span class="v" id="r-iptv">—</span><span class="s" id="r-iptv-s">channels online</span></div>`;
  refreshIptv();
}

// Online / total as the one key number; lag and offline underneath
async function refreshIptv() {
  const d = await getJSON("/api/iptv").catch(() => null);
  if (!d?.counts || !$("r-iptv")) return;
  $("r-iptv").textContent = `${d.counts.online} / ${d.counts.total}`;
  $("r-iptv-s").textContent = `online · ${d.counts.lag} lag · ${d.counts.offline} offline`;
}

async function promValue(q) {
  try {
    const d = await getJSON(`/api/prom/query?${new URLSearchParams({ query: q })}`);
    const v = d.data?.result?.[0]?.value?.[1];
    return v === undefined || Number.isNaN(Number(v)) ? null : Number(v);
  } catch { return null; }
}

async function refreshRail() {
  await Promise.all([...RAIL.map((x, i) => [x, `a${i}`]), ...SERVICES.map((x, i) => [x, `b${i}`])].map(async ([x, id]) => {
    $(`r-${id}`).textContent = x.f(await promValue(x.q));
  }));
}

// ---------- dock ----------
function buildDock(apps = DOCK) {
  $("dock").innerHTML = apps.map((a) => `
    <a class="dock-app" href="${esc(a.href)}" target="_blank" rel="noopener" title="${esc(a.name)}">
      ${a.mono ? `<span class="dock-icon mono" style="--icon:url('../icons/${esc(a.icon)}')"></span>`
               : `<span class="dock-icon"><img src="../icons/${esc(a.icon)}" alt=""></span>`}
      <span class="dock-label">${esc(a.name)}</span></a>`).join("");
}

// What Settings chose. Until it arrives, or if it can't be read, the built-in defaults stay.
async function applySettings() {
  const layout = await getJSON("/api/layout").catch(() => null);
  if (!layout) return;
  RAIL = applyLayout(RAIL_DEFAULT, layout.rail.nas);
  SERVICES = applyLayout(SERVICES_DEFAULT, layout.rail.services);
  buildRail();
  refreshRail();
  buildDock(layout.dock.filter((a) => a.id !== "home").map((a) => ({ ...a, href: at(a.port, a.scheme) })));
}

// ---------- log out ----------
$("logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  location.href = "/";
});

// ---------- start ----------
renderHello(); buildRail(); buildDock();
refreshAttention(); refreshArrivals(); refreshRail(); applySettings();
news.start();
const every = (ms, fn) => setInterval(() => { if (!document.hidden) fn(); }, ms);
every(15000, refreshAttention);
every(15000, refreshRail);
every(60000, refreshArrivals);
every(300000, refreshIptv);
every(300000, () => news.refresh(true));
every(30000, renderHello);
document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshAttention(); refreshRail(); } });
