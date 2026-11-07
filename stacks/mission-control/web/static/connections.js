// Connections card: live globe preview in the rail; expanded = big draggable globe over the main flow.
import { mountGlobe } from "./globe.js";
import { connectionSummary, describe } from "./geo.js";
import { go } from "./app.js";
import { esc } from "./lib.js";

const $ = (id) => document.getElementById(id);
const EXPANDED_MS = 5000;
let netState = null, preview = null, big = null, timer = null;

async function fetchState() {
  const r = await fetch("/api/netwatch");
  if (r.status === 401) location.reload();   // session ended: the reload lands on the login
  if (!r.ok) throw new Error("netwatch " + r.status);
  netState = await r.json();
  return netState;
}

function headerLine() {
  const s = netState?.summary;
  if (!s) return "Netwatch is not answering";
  const flagged = s.flagged_24h ? ` · <span class="flagged">${s.flagged_24h} flagged</span>` : " · 0 flagged";
  return `${s.internet_24h} addresses in 24 h${flagged} · drag to turn, scroll to zoom`;
}

export const connections = {
  id: "connections",
  railHtml: `
    <button class="card globe-card" data-id="connections" aria-expanded="false" aria-controls="panel">
      <span class="t"><span>Connections</span><span class="chev" aria-hidden="true">›</span></span>
      <span class="globe-mount" id="globe-preview"></span>
      <span class="s" id="cs-connections">&nbsp;</span>
    </button>`,

  async refresh() {
    if (!$("cs-connections")) return;   // hidden in Settings
    try {
      await fetchState();
      $("cs-connections").textContent = connectionSummary(netState);
    } catch {
      $("cs-connections").textContent = "unavailable";
      return;
    }
    if (!preview && typeof Globe !== "undefined") {
      try { preview = mountGlobe($("globe-preview"), { interactive: false }); } catch { preview = null; }
    }
    preview?.update(netState);
  },

  open(panel) {
    preview?.pause();   // only one globe draws at a time
    panel.className = "panel globe-panel";
    panel.innerHTML = `
      <div class="globe-mount" id="globe-big"></div>
      <header class="head">
        <div class="head-text">
          <p class="eyebrow">Connections · from home</p>
          <p class="hero" id="g-hero">—</p>
          <p class="context" id="g-context">&nbsp;</p>
        </div>
        <div class="head-right">
          <a class="open" href="http://${location.hostname}:8790" target="_blank" rel="noopener">Open Netwatch ↗</a>
          <button class="close" id="g-close" aria-label="Close">✕</button>
        </div>
      </header>`;
    $("g-close").onclick = () => go({ open: null });
    const show = () => {
      $("g-hero").textContent = netState?.summary ? `${netState.summary.live} live` : "—";
      $("g-context").innerHTML = headerLine();
    };
    show();
    try {
      big = mountGlobe($("globe-big"), {
        interactive: true,
        onHover: (it) => { $("g-context").innerHTML = it ? describe(it) : headerLine(); },
      });
    } catch (e) {
      const why = location.search.includes("static") ? ` (${esc(e.message)})` : "";
      $("globe-big").innerHTML = `<p class="empty">The 3D globe needs WebGL, which this browser has turned off.${why}</p>`;
    }
    const tick = () => fetchState().then(() => { big?.update(netState); show(); }).catch(show);
    if (netState) big?.update(netState);
    tick();
    timer = setInterval(() => { if (!document.hidden) tick(); }, EXPANDED_MS);
  },

  close() {
    clearInterval(timer);
    big?.destroy();
    big = null;
    preview?.resume();
  },
};
