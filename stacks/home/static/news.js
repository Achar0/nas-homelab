// News carousel shared by the guest page and the owner's page: topic tabs, two cards, arrows, swipe.
import { esc, formatAgo, arrowAction } from "./lib.js";
import { mountCarousel } from "./carousel.js";

const $ = (id) => document.getElementById(id);
const TOPIC_LABEL = { tech: "Tech", markets: "Markets", discoveries: "Discovery" };

// topics: { key: label }. onOpen(id): record a story being opened (the owner's page only).
export function mountNews({ getJSON, topics, onOpen, keysBlocked = () => false }) {
  let topic = "all";
  try {
    const saved = sessionStorage.getItem("home.topic");
    if (saved in topics) topic = saved;
  } catch { /* private mode */ }

  const carousel = mountCarousel($("deck"), $("track"), {
    onIndex(i, count, visible) {
      const last = Math.min(i + visible, count);
      $("count").textContent = count ? `${visible > 1 && last > i + 1 ? `${i + 1}–${last}` : i + 1} / ${count}` : "0 / 0";
      $("prev").disabled = i <= 0;
      $("next").disabled = i >= count - visible;
      try { sessionStorage.setItem("home.index", String(i)); } catch { /* private mode */ }
    },
  });

  const storyHtml = (s) => `<article class="story ${esc(s.topic)}">
    <span class="tag">${esc(TOPIC_LABEL[s.topic] || s.topic)} · ${esc(s.lang.toUpperCase())}</span>
    <h3>${esc(s.title)}</h3>
    <p>${esc(s.summary)}</p>
    <footer><span>${esc(s.source)} · ${s.opened_at ? `opened ${esc(formatAgo(s.opened_at))}` : esc(formatAgo(s.published))}</span>
      <a href="${esc(s.link)}" target="_blank" rel="noopener"${onOpen ? ` data-open="${esc(s.id)}"` : ""}>Read more ↗</a></footer>
  </article>`;

  function renderTopics() {
    $("topics").innerHTML = Object.entries(topics).map(([k, v]) =>
      `<button role="tab" data-t="${k}" aria-selected="${k === topic}">${v}</button>`).join("");
  }

  async function refresh(keep = true) {
    let data;
    try { data = await getJSON(`/api/news?topic=${topic}`); } catch { return; }
    const html = (data.items || []).map(storyHtml).join("") ||
      `<div class="empty">${topic === "opened" ? "Stories you open appear here for 30 days" : data.updated ? "No stories right now" : "Fetching the news…"}</div>`;
    carousel.set(html, keep);
  }

  $("topics").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.dataset.t === topic) return;
    topic = b.dataset.t;
    try { sessionStorage.setItem("home.topic", topic); sessionStorage.setItem("home.index", "0"); } catch { /* ignore */ }
    renderTopics();
    refresh(false);
  });
  if (onOpen) {
    $("track").addEventListener("click", (e) => {
      const a = e.target.closest("a[data-open]");
      if (a) onOpen(a.dataset.open);
    });
  }
  $("prev").addEventListener("click", () => carousel.prev());
  $("next").addEventListener("click", () => carousel.next());
  document.addEventListener("keydown", (e) => {
    if (keysBlocked() || e.target.closest("input, textarea, select, [contenteditable]")) return;
    const act = arrowAction(e);
    if (act) { carousel[act](); e.preventDefault(); }
  });

  renderTopics();
  return {
    refresh,
    // first load: back to the card you were on
    start: () => refresh(false).then(() => {
      let saved = 0;
      try { saved = Number(sessionStorage.getItem("home.index") || 0); } catch { /* private mode */ }
      for (let i = 0; i < saved; i++) carousel.next();
    }),
  };
}
