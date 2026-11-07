// Pure helpers: time ranges, number formatting, chart data shaping. No DOM here (tested with node --test).

// Range -> how far back, and the step between points (keeps every chart at ~240-1460 points)
export const RANGES = {
  "1H": { seconds: 3600, step: 15 },
  "24H": { seconds: 86400, step: 60 },
  "1W": { seconds: 604800, step: 600 },
  "1M": { seconds: 2592000, step: 1800 },
  "1Y": { seconds: 31536000, step: 21600 },
};

// Window for rate(): short ranges get a few steps of smoothing; long ranges (step >= 10 min) use
// exactly one step, so each sample is read once (a 1Y chart would otherwise read everything 4x)
export const rateWindow = (step) => `${step >= 600 ? step : Math.max(4 * step, 60)}s`;

// 1W/1M/1Y points change every 10 min to 6 h: no need to refetch them every minute
export const autoRefresh = (range) => RANGES[range].step < 600;

const ok = (n) => n !== null && n !== undefined && Number.isFinite(n);
const DASH = "—";

// 1 significant decimal below 10, none above: 1.8 / 22 / 912
const short = (n) => (n < 10 ? String(Math.round(n * 10) / 10) : String(Math.round(n)));

function scaled(n, units, base) {
  let i = 0;
  while (Math.abs(n) >= base && i < units.length - 1) { n /= base; i++; }
  return `${short(n)} ${units[i]}`;
}

export const formatBytes = (n) => (ok(n) ? scaled(n, ["B/s", "KB/s", "MB/s", "GB/s"], 1000) : DASH);
export const formatSize = (n) => (ok(n) ? scaled(n, ["B", "KB", "MB", "GB", "TB"], 1000) : DASH);
export const formatBitrate = (n) => (ok(n) ? scaled(n, ["b/s", "Kb/s", "Mb/s", "Gb/s"], 1000) : DASH);
export const formatPercent = (n) => (ok(n) ? `${short(n)}%` : DASH);
export const formatTemp = (n) => (ok(n) ? `${Math.round(n)}°C` : DASH);
export const formatMs = (n) => (ok(n) ? `${short(n)} ms` : DASH);
export const formatCount = (n) => (ok(n) ? Math.round(n).toLocaleString("en-US") : DASH);
export const formatPlain = (n) => (ok(n) ? short(n) : DASH);

// last / average / peak of the real points (null and NaN are gaps, not zeros)
export function summarize(points) {
  let sum = 0, count = 0, peak = null, peakIndex = -1, last = null;
  points.forEach((v, i) => {
    if (!ok(v)) return;
    sum += v; count++; last = v;
    if (peak === null || v > peak) { peak = v; peakIndex = i; }
  });
  return { last, avg: count ? sum / count : null, peak, peakIndex };
}

// Prometheus matrix -> uPlot columns on a fixed time grid; missing samples become null
export function toSeries(result, start, end, step) {
  const x = [];
  for (let t = start; t <= end; t += step) x.push(t);
  const index = new Map(x.map((t, i) => [t, i]));
  const ys = result.map((r) => {
    const col = new Array(x.length).fill(null);
    for (const [t, v] of r.values) {
      const i = index.get(Math.round(t));
      if (i !== undefined) col[i] = Number(v);
    }
    return col;
  });
  return { x, ys };
}

// "2 h ago" style relative time (unix seconds)
export function formatAgo(t, now = Date.now() / 1000) {
  if (!ok(t)) return DASH;
  const s = Math.max(0, now - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

// A card shows "—" when its source is down (mc_up 0 / missing) or its key number is missing
export const unavailable = (up, value) => up !== 1 || !ok(value);

// Escape text before it goes into innerHTML (Prometheus labels, device names, Netwatch strings)
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => (v === null || v === undefined ? "" : String(v).replace(/[&<>"']/g, (c) => ESC[c]));

// Settings: items in order's sequence; show:false left out, unknown ids ignored, items order doesn't name stay at the end
export function applyLayout(items, order) {
  if (!order) return items;
  const byId = new Map(items.map((x) => [x.id, x]));
  const out = [];
  for (const o of order) {
    if (byId.has(o.id) && o.show !== false) out.push(byId.get(o.id));
  }
  const named = new Set(order.map((o) => o.id));
  return out.concat(items.filter((x) => !named.has(x.id)));
}
