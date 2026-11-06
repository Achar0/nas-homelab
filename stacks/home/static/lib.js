// Pure helpers for the Home page (tested with node --test)

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
// Escape text before it goes into innerHTML (feed text, Netwatch strings, show names)
export const esc = (v) => (v === null || v === undefined ? "" : String(v).replace(/[&<>"']/g, (c) => ESC[c]));

export function formatAgo(t, now = Date.now() / 1000) {
  if (!Number.isFinite(t) || t <= 0) return "—";
  const s = Math.max(0, now - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

// Carousel: move one card at a time; the first visible index never passes count - visible
export function step(index, delta, count, visible = 1) {
  const last = Math.max(0, count - visible);
  return Math.min(last, Math.max(0, Math.min(index, last) + delta));
}

export const visibleCount = (width) => (width >= 700 ? 2 : 1);

export function greeting(hour) {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  if (hour >= 18 && hour < 23) return "Good evening";
  return "Good night";
}

// News keys: plain ← → only; with Alt/Ctrl/Cmd/Shift the browser keeps its own shortcuts (back/forward…)
export function arrowAction(e) {
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return null;
  return e.key === "ArrowRight" ? "next" : e.key === "ArrowLeft" ? "prev" : null;
}
