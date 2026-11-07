import test from "node:test";
import assert from "node:assert/strict";
import { autoRefresh, applyLayout } from "./lib.js";
import { RANGES, rateWindow, formatBytes, formatBitrate, formatPercent, formatTemp, summarize, toSeries } from "./lib.js";

test("ranges", () => {
  assert.deepEqual(Object.keys(RANGES), ["1H", "24H", "1W", "1M", "1Y"]);
  assert.equal(RANGES["24H"].seconds, 86400);
  assert.equal(RANGES["24H"].step, 60);
});

test("rateWindow: smooth on short ranges, each sample read once on long ones", () => {
  assert.equal(rateWindow(15), "60s");
  assert.equal(rateWindow(60), "240s");
  assert.equal(rateWindow(600), "600s");
  assert.equal(rateWindow(21600), "21600s");
});

test("only short ranges auto-refresh", () => {
  assert.equal(autoRefresh("1H"), true);
  assert.equal(autoRefresh("24H"), true);
  assert.equal(autoRefresh("1W"), false);
  assert.equal(autoRefresh("1Y"), false);
});

test("formatters", () => {
  assert.equal(formatBytes(1_800_000), "1.8 MB/s");
  assert.equal(formatBytes(950), "950 B/s");
  assert.equal(formatBytes(22_400), "22 KB/s");
  assert.equal(formatBitrate(912_000_000), "912 Mb/s");
  assert.equal(formatBitrate(1_200_000_000), "1.2 Gb/s");
  assert.equal(formatPercent(12.34), "12%");
  assert.equal(formatPercent(0.4), "0.4%");
  assert.equal(formatTemp(47.2), "47°C");
  assert.equal(formatBytes(null), "—");
});

test("summary ignores nulls", () => {
  assert.deepEqual(summarize([1, null, 3, NaN, 2]), { last: 2, avg: 2, peak: 3, peakIndex: 2 });
});

test("summary of no data", () => {
  assert.deepEqual(summarize([null, null]), { last: null, avg: null, peak: null, peakIndex: -1 });
  assert.deepEqual(summarize([]), { last: null, avg: null, peak: null, peakIndex: -1 });
});

test("toSeries fills gaps with null", () => {
  const prom = [{ values: [[100, "1"], [130, "3"]] }, { values: [[115, "5"]] }];
  const s = toSeries(prom, 100, 130, 15);
  assert.deepEqual(s.x, [100, 115, 130]);
  assert.deepEqual(s.ys, [[1, null, 3], [null, 5, null]]);
  assert.equal(s.x.length, (130 - 100) / 15 + 1);
});

import { formatAgo, unavailable } from "./lib.js";

test("formatAgo", () => {
  assert.equal(formatAgo(1000, 1030), "just now");
  assert.equal(formatAgo(1000, 1000 + 5 * 60), "5 min ago");
  assert.equal(formatAgo(1000, 1000 + 2 * 3600 + 100), "2 h ago");
  assert.equal(formatAgo(1000, 1000 + 3 * 86400), "3 days ago");
  assert.equal(formatAgo(null, 5), "—");
});

test("card unavailable when source down or value missing", () => {
  assert.equal(unavailable(0, 12), true);
  assert.equal(unavailable(1, null), true);
  assert.equal(unavailable(null, 5), true);
  assert.equal(unavailable(1, 0), false);
});

import { esc } from "./lib.js";

test("esc neutralises markup", () => {
  assert.equal(esc('<img src=x onerror="alert(1)">&'), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;");
  assert.equal(esc("it's"), "it&#39;s");
  assert.equal(esc(null), "");
  assert.equal(esc(42), "42");
});

test("applyLayout follows order, hides, appends missing, ignores unknown", () => {
  const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
  const ids = (l) => l.map((x) => x.id);
  assert.deepEqual(ids(applyLayout(items, [{ id: "c", show: true }, { id: "b", show: false }, { id: "zzz", show: true }])), ["c", "a"]);
  assert.deepEqual(ids(applyLayout(items, null)), ["a", "b", "c"]);
});
