import test from "node:test";
import assert from "node:assert/strict";
import { esc, formatAgo, step, visibleCount, greeting, fmtTB, fmtMbps, otherLabel } from "./lib.js";

test("step clamps at both ends", () => {
  assert.equal(step(0, -1, 10), 0);
  assert.equal(step(0, 1, 10), 1);
  assert.equal(step(8, 1, 10, 2), 8);      // last pair: 8 and 9 already visible
  assert.equal(step(3, 1, 0), 0);
  assert.equal(step(5, 1, 3, 2), 1);       // list shrank under us
});

test("visible cards per width", () => {
  assert.equal(visibleCount(1920), 2);
  assert.equal(visibleCount(1024), 2);
  assert.equal(visibleCount(400), 1);
});

test("esc", () => {
  assert.equal(esc('<a href="x">&</a>'), "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;");
  assert.equal(esc(undefined), "");
});

test("formatAgo", () => {
  assert.equal(formatAgo(1000, 1030), "just now");
  assert.equal(formatAgo(1000, 1000 + 7200), "2 h ago");
});

test("greeting by hour", () => {
  assert.equal(greeting(7), "Good morning");
  assert.equal(greeting(14), "Good afternoon");
  assert.equal(greeting(20), "Good evening");
  assert.equal(greeting(2), "Good night");
});

import { arrowAction } from "./lib.js";

test("only plain arrows move the cards", () => {
  const k = (key, mods = {}) => ({ key, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, ...mods });
  assert.equal(arrowAction(k("ArrowRight")), "next");
  assert.equal(arrowAction(k("ArrowLeft")), "prev");
  assert.equal(arrowAction(k("ArrowLeft", { altKey: true })), null);    // browser back
  assert.equal(arrowAction(k("ArrowRight", { metaKey: true })), null);
  assert.equal(arrowAction(k("ArrowRight", { ctrlKey: true })), null);
  assert.equal(arrowAction(k("ArrowRight", { shiftKey: true })), null);
  assert.equal(arrowAction(k("ArrowUp")), null);
});

test("fmtTB", () => {
  assert.equal(fmtTB(3.2e12), "3.2 TB");
  assert.equal(fmtTB(250e9), "250 GB");
  assert.equal(fmtTB(null), "—");
});

test("fmtMbps", () => {
  assert.equal(fmtMbps(936e6), "936 Mb/s");
  assert.equal(fmtMbps(null), "—");
});

test("otherLabel", () => {
  assert.equal(otherLabel(0), "");
  assert.equal(otherLabel(1), "1 other download");
  assert.equal(otherLabel(3), "3 other downloads");
});
