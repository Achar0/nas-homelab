// Two-card news carousel: one card per step (buttons, ← → keys, swipe that follows the finger).
import { step, visibleCount } from "./lib.js";

export function mountCarousel(deck, track, { onIndex = () => {} } = {}) {
  let index = 0, count = 0, visible = 2;

  const offset = (i) => {
    const card = track.children[i];
    return card ? card.offsetLeft : 0;
  };
  function place(animate = true) {
    track.style.transition = animate ? "" : "none";
    track.style.transform = `translateX(${-offset(index)}px)`;
    onIndex(index, count, visible);
  }
  function go(delta) {
    const next = step(index, delta, count, visible);
    if (next !== index) { index = next; place(); }
  }
  function measure() {
    visible = visibleCount(deck.clientWidth);
    track.style.setProperty("--visible", visible);
    index = step(index, 0, count, visible);
    place(false);
  }

  // Swipe / drag: the track follows the pointer 1:1, then settles one card over if the
  // gesture went far enough or was a quick flick
  let startX = null, startY = 0, startT = 0, base = 0, dx = 0, horizontal = null;
  deck.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest("a")) return;
    startX = e.clientX; startY = e.clientY; startT = performance.now(); dx = 0; horizontal = null;
    base = -offset(index);
  });
  deck.addEventListener("pointermove", (e) => {
    if (startX === null) return;
    dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (horizontal === null && Math.hypot(dx, dy) > 8) {
      horizontal = Math.abs(dx) > Math.abs(dy);
      if (horizontal) deck.setPointerCapture(e.pointerId);
    }
    if (!horizontal) return;
    const atEdge = (dx > 0 && index === 0) || (dx < 0 && index >= count - visible);
    const shown = atEdge ? dx * 0.3 : dx;   // rubber-band at the ends
    track.style.transition = "none";
    track.style.transform = `translateX(${base + shown}px)`;
  });
  const end = () => {
    if (startX === null) return;
    const fast = Math.abs(dx) / Math.max(1, performance.now() - startT) > 0.5;
    startX = null;
    if (!horizontal) return;
    if (Math.abs(dx) > 40 || (fast && Math.abs(dx) > 12)) go(dx < 0 ? 1 : -1);
    else place();
  };
  deck.addEventListener("pointerup", end);
  deck.addEventListener("pointercancel", end);

  new ResizeObserver(measure).observe(deck);

  return {
    set(nodesHtml, keepIndex = true) {
      track.innerHTML = nodesHtml;
      count = track.children.length;
      if (!keepIndex) index = 0;
      measure();
    },
    next: () => go(1),
    prev: () => go(-1),
    get index() { return index; },
  };
}
