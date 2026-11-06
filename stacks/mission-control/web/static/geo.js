// Netwatch /api/state -> globe data (pure; tested with node --test)
import { esc } from "./lib.js";

export const COLORS = { live: "#30D158", past: "rgba(10,132,255,0.35)", flagged: "#FF453A" };
const ORDER = { past: 0, live: 1, flagged: 2 };   // flagged last = drawn on top

const kindOf = (it) => (it.flag?.length ? "flagged" : it.live ? "live" : "past");

// One arc per place (rounded to 0.5°): fewer arcs = smooth zooming. The most severe connection
// there decides the colour and is what hovering describes; count says how many share it.
const cell = (v) => Math.round(v * 2) / 2;

export function arcsFromState(state) {
  const home = state?.home;
  if (!home || !Array.isArray(state.items)) return [];
  const byPlace = new Map();
  for (const it of state.items) {
    if (!it.geo || !Number.isFinite(it.geo.lat) || !Number.isFinite(it.geo.lon)) continue;
    const key = `${cell(it.geo.lat)},${cell(it.geo.lon)}`;
    const kind = kindOf(it);
    const arc = byPlace.get(key);
    if (!arc) {
      byPlace.set(key, { startLat: home.lat, startLng: home.lon, endLat: it.geo.lat, endLng: it.geo.lon, kind, item: it, count: 1 });
      continue;
    }
    arc.count++;
    if (ORDER[kind] > ORDER[arc.kind]) Object.assign(arc, { kind, item: it, endLat: it.geo.lat, endLng: it.geo.lon });
  }
  return [...byPlace.values()].sort((a, b) => ORDER[a.kind] - ORDER[b.kind]);
}

export function ringsFromState(state) {
  if (!Array.isArray(state?.items)) return [];
  return state.items.filter((it) => it.flag?.length && it.geo).map((it) => ({ lat: it.geo.lat, lng: it.geo.lon, item: it }));
}

export function connectionSummary(state) {
  const s = state?.summary || {};
  if (s.live === undefined) return "—";
  return `${s.live} live · ${s.internet_24h ?? 0} in 24 h · ${s.flagged_24h ?? 0} flagged`;
}

export function describe(it) {
  const where = it.geo ? [it.geo.city, it.geo.country].filter(Boolean).join(", ") : "local network";
  const what = (it.services || []).join(", ");
  const flag = it.flag?.length ? ` · <span class="flagged">${esc(it.flag[0])}</span>` : "";
  const more = it.count > 1 ? ` · ${Number(it.count)} connections here` : "";
  return `<b>${esc(it.ip)}</b> · ${esc(where)}${what ? ` · ${esc(what)}` : ""}${more}${flag}`;
}
