import test from "node:test";
import assert from "node:assert/strict";
import { arcsFromState, ringsFromState, connectionSummary } from "./geo.js";

const st = {
  home: { lat: 45.46, lon: 9.19 },
  summary: { live: 2, internet_24h: 3, flagged_24h: 1 },
  items: [
    { ip: "1.1.1.1", live: true, flag: [], geo: { lat: 10, lon: 20, city: "A", country: "X" }, services: ["HTTPS"] },
    { ip: "2.2.2.2", live: false, flag: ["Inbound"], geo: { lat: 30, lon: 40, city: "B", country: "Y" }, services: ["port 1"] },
    { ip: "3.3.3.3", live: false, flag: [], geo: { lat: 50, lon: 60, city: "C", country: "Z" }, services: [] },
    { ip: "192.168.1.27", live: true, flag: [], geo: null, services: ["SSH"] },
  ],
};

test("arcs: one per geolocated item, from home, coloured by state", () => {
  const arcs = arcsFromState(st);
  const by = Object.fromEntries(arcs.map((a) => [a.item.ip, a]));
  assert.equal(arcs.length, 3);
  const a = by["1.1.1.1"];
  assert.deepEqual([a.startLat, a.startLng, a.endLat, a.endLng], [45.46, 9.19, 10, 20]);
  assert.equal(a.kind, "live");
  assert.equal(by["2.2.2.2"].kind, "flagged");
  assert.equal(by["3.3.3.3"].kind, "past");
});

test("flagged drawn last so they sit on top", () => {
  const kinds = arcsFromState(st).map((a) => a.kind);
  assert.equal(kinds.at(-1), "flagged");
});

test("rings only for flagged items", () => {
  const rings = ringsFromState(st);
  assert.deepEqual(rings.map((r) => [r.lat, r.lng]), [[30, 40]]);
});

test("summary line", () => {
  assert.equal(connectionSummary(st), "2 live · 3 in 24 h · 1 flagged");
  assert.equal(connectionSummary({ summary: {} }), "—");
});

test("missing state is safe", () => {
  assert.deepEqual(arcsFromState(null), []);
  assert.deepEqual(ringsFromState({ items: null }), []);
});

import { describe as describeItem } from "./geo.js";

test("describe escapes every field", () => {
  const html = describeItem({ ip: "<b>x</b>", geo: { city: "<script>", country: "Y" }, services: ["<i>s</i>"], flag: ["<u>f</u>"] });
  assert.ok(!/<(b>x|script|i>s|u>f)/.test(html), html);
  assert.ok(html.includes("&lt;script&gt;"));
});

test("arcs to the same place merge into one (most severe kind wins)", () => {
  const s = {
    home: { lat: 45, lon: 9 },
    items: [
      { ip: "a", live: false, flag: [], geo: { lat: 52.37, lon: 4.89 } },
      { ip: "b", live: true, flag: [], geo: { lat: 52.41, lon: 4.92 } },
      { ip: "c", live: false, flag: ["x"], geo: { lat: 52.36, lon: 4.9 } },
      { ip: "d", live: false, flag: [], geo: { lat: 40.7, lon: -74 } },
    ],
  };
  const arcs = arcsFromState(s);
  assert.equal(arcs.length, 2);
  const ams = arcs.find((a) => Math.round(a.endLat) === 52);
  assert.equal(ams.count, 3);
  assert.equal(ams.kind, "flagged");
  assert.equal(ams.item.ip, "c");
});
