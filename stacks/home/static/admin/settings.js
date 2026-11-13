// Settings page: every change saves at once through /api/settings/*, then the page redraws from the server.
import { esc, moveItem } from "/lib.js";
import { bufToB64url, toCreateOptions, passkeysAvailable } from "/passkey.js";

const $ = (id) => document.getElementById(id);
const at = (port, scheme = "http") => `${scheme}://${location.hostname}:${port}`;
const pane = $("pane");

const SECTIONS = { feeds: "News feeds", alerts: "Alert rules", services: "Services & dock", apps: "Apps", account: "Account" };
const TOPICS = { tech: "Tech", markets: "Markets", discoveries: "Discoveries" };
const LANGS = { en: "EN", it: "IT" };
const ALERTS = [   // limits match settings.ALERT_LIMITS; the server checks them again
  { key: "free_pct", name: "Free space low", hint: "Warn below", min: 5, max: 50, step: 5, unit: "%" },
  { key: "service_down_min", name: "Service down", hint: "Urgent after", min: 1, max: 60, step: 1, unit: " min" },
  { key: "intrusion_min", name: "Possible intrusion", hint: "Urgent after it lasts", min: 1, max: 60, step: 1, unit: " min" },
  { key: "hot_c", name: "Drive running hot", hint: "Warn above", min: 40, max: 70, step: 1, unit: " °C" },
  { key: "slow_pct", name: "Slow internet", hint: "Warn below this share of the usual speed", min: 10, max: 90, step: 5, unit: "%" },
];
const LABELS = { cpu: "CPU", memory: "Memory", temperature: "Temperature", free: "Free space", qbittorrent: "qBittorrent",
  adguard: "AdGuard", speedtest: "Speedtest", tailscale: "Tailscale", connections: "Connections" };
const TABS = { dock: "Dock", rail: "Home rail", cards: "Mission Control cards" };

let S = null;                 // the settings, as last read from the server
let section = SECTIONS[location.hash.slice(1)] ? location.hash.slice(1) : "feeds";
let tab = "dock";
let passkeyList = null;       // null while loading; [] when none, or when this address can't use passkeys
let passkeyOk = false;        // secure context with WebAuthn
let armed = null;             // the destructive button waiting for its second click

// ---------- talking to the server ----------
async function post(path, body = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null);
  if (!r) return { ok: false, status: 0, data: { error: "Couldn't reach the NAS." } };
  if (r.status === 401) { location.reload(); return { ok: false, status: 401, data: {} }; }   // session ended: this lands on the login
  return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
}

async function load() {
  const r = await fetch("/api/settings").catch(() => null);
  if (!r) return false;
  if (r.status === 401) { location.reload(); return false; }
  if (!r.ok) return false;
  S = await r.json();
  return true;
}

let toastTimer;
function toast(text, bad = false) {
  const t = $("toast");
  t.textContent = text;
  t.classList.toggle("bad", bad);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 2500);
}

// The passkey list; off the HTTPS name the server answers 404 and the section shows the secure-address line
async function loadPasskeys() {
  passkeyOk = await passkeysAvailable();
  passkeyList = [];
  if (!passkeyOk) return;
  const r = await fetch("/api/passkeys").catch(() => null);
  if (r?.ok) passkeyList = (await r.json()).passkeys;
  else passkeyOk = false;
}

// Save, then redraw from what the server really has, so a refused change goes back by itself
async function save(path, body) {
  const r = await post(path, body);
  if (!r.ok && r.status !== 401) toast(r.data.error || "That couldn't be saved.", true);
  await load();
  render();
  return r.ok;
}

// ---------- small pieces ----------
const toggle = (on, label, attrs, disabled = false) =>
  `<button class="tog" role="switch" aria-checked="${on}" aria-label="${esc(label)}" ${attrs}${disabled ? " disabled" : ""}></button>`;

function confirmButton(key, label, confirm) {
  return `<button class="danger" data-act="arm" data-key="${esc(key)}">${esc(armed === key ? confirm : label)}</button>`;
}

const moveButtons = (list, id, i, n) => `<span class="move">
  <button data-act="move" data-list="${list}" data-id="${esc(id)}" data-to="${i - 1}" data-key="up-${list}-${esc(id)}" aria-label="Move up"${i === 0 ? " disabled" : ""}>↑</button>
  <button data-act="move" data-list="${list}" data-id="${esc(id)}" data-to="${i + 1}" data-key="down-${list}-${esc(id)}" aria-label="Move down"${i === n - 1 ? " disabled" : ""}>↓</button>
</span>`;

// ---------- sections ----------
function drawFeeds() {
  const rows = S.feeds.map((f) => `<div class="row">
    ${toggle(f.enabled, `Show ${f.name}`, `data-act="feed-on" data-id="${esc(f.id)}" data-key="feed-${esc(f.id)}"`)}
    <div class="grow">${esc(f.name)}</div>
    <span class="meta">${esc(TOPICS[f.topic])} · ${esc(LANGS[f.lang])}</span>
    ${confirmButton(`rm-${f.id}`, "Remove", "Really remove?")}
  </div>`).join("");
  const options = (o) => Object.entries(o).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  return `<h2>News feeds</h2><p class="sub">What shows up in News on Home and on the guest page.</p>
    <div class="group">${rows || `<div class="row"><span class="meta">No feeds yet.</span></div>`}</div>
    <form class="group add" id="add-feed">
      <input id="f-url" type="url" required placeholder="https://example.com/feed.xml" aria-label="Feed address">
      <select id="f-topic" aria-label="Topic">${options(TOPICS)}</select>
      <select id="f-lang" aria-label="Language">${options(LANGS)}</select>
      <button class="btn" id="f-add">Add</button>
    </form>`;
}

function drawAlerts() {
  const kuma = S.services.find((s) => s.id === "kuma");
  const kumaLink = kuma?.port ? ` <a href="${at(kuma.port, kuma.scheme)}/settings/notifications" target="_blank" rel="noopener">Open its settings ↗</a>` : "";
  const rows = ALERTS.map((a) => {
    const v = S.alerts[a.key];
    return `<div class="row"><div class="grow">${a.name}<small>${a.hint}</small></div>
      <div class="stepper">
        <button data-act="step" data-k="${a.key}" data-v="${Math.max(a.min, v - a.step)}" data-key="less-${a.key}" aria-label="Less"${v <= a.min ? " disabled" : ""}>−</button>
        <output>${v}${a.unit}</output>
        <button data-act="step" data-k="${a.key}" data-v="${Math.min(a.max, v + a.step)}" data-key="more-${a.key}" aria-label="More"${v >= a.max ? " disabled" : ""}>+</button>
      </div></div>`;
  }).join("");
  return `<h2>Alert rules</h2><p class="sub">When Home warns you, and when your phone buzzes.</p>
    <div class="group"><div class="row"><div class="grow">Phone notifications
      <small>Urgent alerts from Home and Netwatch. Alerts still show on Home when this is off. Uptime Kuma sends its own.${kumaLink}</small></div>
      ${toggle(S.alerts.push, "Phone notifications", `data-act="push" data-key="push"`)}</div></div>
    <div class="group">${rows}</div>`;
}

// The port goes in the description when the container's name doesn't already carry it
function serviceDescription(s) {
  if (s.container && s.port && s.container.endsWith(`-${s.port}`)) return s.container;
  const port = s.port ? `:${s.port}` : "";
  return s.container && !port ? s.container : port;
}

function portControl(s) {
  if (s.port_options.length) {
    const opts = s.port_options.map((p) => `<option value="${p}"${p === s.port ? " selected" : ""}>${p}</option>`).join("");
    return `<select data-act="port" data-id="${esc(s.id)}" data-key="port-${esc(s.id)}" aria-label="Port for ${esc(s.name)}">
      ${s.port ? "" : `<option value="">Pick a port</option>`}${opts}</select>`;
  }
  return `<input class="port-input" type="number" min="1" max="65535" placeholder="Port" value="${s.port ?? ""}"
    data-act="port" data-id="${esc(s.id)}" data-key="port-${esc(s.id)}" aria-label="Port for ${esc(s.name)}">`;
}

function schemeControl(s) {
  return `<select data-act="scheme" data-id="${esc(s.id)}" data-key="scheme-${esc(s.id)}" aria-label="Scheme for ${esc(s.name)}">
    ${["http", "https"].map((x) => `<option${x === s.scheme ? " selected" : ""}>${x}</option>`).join("")}</select>`;
}

const nameInput = (s) => `<input class="name-input" value="${esc(s.name)}" maxlength="40" data-act="name" data-id="${esc(s.id)}" data-key="name-${esc(s.id)}" aria-label="Name for ${esc(s.container)}">`;

function drawNew(rows) {
  if (!rows.length) return "";
  return `<h3>New</h3><div class="group">${rows.map((s) => `<div class="row">
    <div class="grow">${nameInput(s)}
      <small>${esc(s.container)}${s.running ? "" : ' · <span class="off-label">not running</span>'}</small></div>
    ${schemeControl(s)}${portControl(s)}
    ${toggle(false, `Show ${s.name} on the dock`, `data-act="dock-on" data-id="${esc(s.id)}" data-key="dock-${esc(s.id)}"`, !s.port)}
    <button class="link" data-act="ignore" data-id="${esc(s.id)}">Ignore</button>
    ${s.running ? "" : `<button class="danger" data-act="remove" data-id="${esc(s.id)}">Remove</button>`}
  </div>`).join("")}</div>`;
}

function drawDock() {
  const fresh = S.services.filter((s) => s.state === "new");
  const known = S.services.filter((s) => s.state === "known");
  const rows = known.map((s, i) => `<div class="row" draggable="true" data-list="dock" data-index="${i}">
    <span class="handle" aria-hidden="true">≡</span>
    <div class="grow">${s.id.startsWith("c-") ? nameInput(s) : esc(s.name)}<small>${esc(serviceDescription(s))}${s.running ? "" : ' · <span class="off-label">not running</span>'}</small></div>
    ${s.id.startsWith("c-") ? schemeControl(s) + portControl(s) : ""}
    ${s.running ? "" : `<button class="danger" data-act="remove" data-id="${esc(s.id)}">Remove</button>`}
    ${moveButtons("dock", s.id, i, known.length)}
    ${toggle(s.on_dock, `Show ${s.name} on the dock`, `data-act="dock-on" data-id="${esc(s.id)}" data-key="dock-${esc(s.id)}"`)}
  </div>`).join("");
  return drawNew(fresh) + `<div class="group">${rows}</div>`;
}

function drawShown(list, items) {
  return `<div class="group">${items.map((x, i) => `<div class="row" draggable="true" data-list="${list}" data-index="${i}">
    <span class="handle" aria-hidden="true">≡</span>
    <div class="grow">${esc(LABELS[x.id] || x.id)}</div>
    ${moveButtons(list, x.id, i, items.length)}
    ${toggle(x.show, `Show ${LABELS[x.id] || x.id}`, `data-act="show" data-list="${list}" data-id="${esc(x.id)}" data-key="show-${list}-${esc(x.id)}"`)}
  </div>`).join("")}</div>`;
}

function drawServices() {
  const tabs = Object.entries(TABS).map(([k, v]) => `<button role="tab" aria-selected="${k === tab}" data-act="tab" data-tab="${k}">${v}</button>`).join("");
  const body = tab === "dock" ? drawDock()
    : tab === "rail" ? `<h3>NAS</h3>${drawShown("rail_nas", S.rail.nas)}<h3>Services</h3>${drawShown("rail_services", S.rail.services)}`
    : drawShown("cards", S.cards);
  const sub = tab === "dock" ? "Home and Mission Control share one dock. A new service appears here by itself, and stays off the dock until you switch it on."
    : "Choose what appears, and in what order.";
  return `<h2>Services &amp; dock</h2><p class="sub">${sub}</p><div class="tabs" role="tablist">${tabs}</div>${body}`;
}

function drawApps() {
  const rows = S.services.filter((s) => s.port && s.state !== "ignored").map((s) => `<div class="row">
    <div class="grow">${esc(s.name)}</div>
    <a href="${at(s.port, s.scheme)}${esc(s.settings_path)}" target="_blank" rel="noopener">${s.settings_path ? "Open settings" : "Open"} ↗</a>
  </div>`).join("");
  return `<h2>Apps</h2><p class="sub">Each app keeps its own settings. These just take you there.</p><div class="group">${rows}</div>`;
}

const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

// The HTTPS address for the hint, built only from a .ts.net host so no tailnet name lives in the code
function secureAddress() {
  return location.hostname.endsWith(".ts.net") ? `https://${location.hostname}:3443` : "the secure address";
}

function drawPasskeys() {
  const head = `<h3>Passkeys</h3>`;
  if (!passkeyOk) return `${head}<div class="group"><div class="row"><div class="grow"><small>Passkeys work on the secure address: open ${esc(secureAddress())}</small></div></div></div>`;
  const rows = (passkeyList || []).map((p) => `<div class="row">
    <div class="grow">${esc(p.name)}<small>Added ${day(p.created)} · Last used ${p.last_used ? day(p.last_used) : "never"}</small></div>
    ${confirmButton(`pk-${p.id}`, "Remove", "Really remove?")}</div>`).join("");
  return `${head}<form class="group" id="add-passkey">${rows}
    <div class="row"><input class="grow" id="pk-name" placeholder="iPhone" maxlength="40" aria-label="Passkey name" autocomplete="off">
      <button class="btn" id="pk-add">Add passkey</button></div></form>`;
}

function drawAccount() {
  const field = (id, label, auto) => `<label class="field" for="${id}">${label}<input id="${id}" type="password" required autocomplete="${auto}"></label>`;
  return `<h2>Account</h2><p class="sub">The one admin password for Home, Mission Control and Netwatch.</p>
    ${drawPasskeys()}
    <h3>Change password</h3>
    <form class="group" id="change-pw">
      ${field("pw-current", "Current password", "current-password")}
      ${field("pw-new", "New password", "new-password")}
      ${field("pw-again", "Repeat new password", "new-password")}
      <div class="row"><span class="grow"><small>Other devices will need the new password. This one stays logged in.</small></span><button class="btn" id="pw-save">Change password</button></div>
    </form>
    <div class="group"><div class="row"><div class="grow">Log out everywhere<small>Every browser and phone will need the password again, including this one.</small></div>
      ${confirmButton("logout-all", "Log out everywhere", "Really log out everywhere?")}</div></div>`;
}

const DRAW = { feeds: drawFeeds, alerts: drawAlerts, services: drawServices, apps: drawApps, account: drawAccount };

function render() {
  if (!S) return;
  const focused = document.activeElement?.dataset?.key;   // redrawing replaces the buttons; keep keyboard users in place
  $("notice").hidden = !S.problem;
  $("notice").textContent = S.problem || "";
  $("nav").innerHTML = Object.entries(SECTIONS).map(([k, v]) => `<button data-s="${k}" aria-current="${k === section}">${esc(v)}</button>`).join("");
  pane.innerHTML = DRAW[section]();
  if (focused) pane.querySelector(`[data-key="${CSS.escape(focused)}"]:not(:disabled)`)?.focus();
}

// ---------- actions ----------
function orderIds(list) {
  if (list === "dock") return S.services.filter((s) => s.state === "known").map((s) => s.id);
  if (list === "cards") return S.cards.map((x) => x.id);
  return S.rail[list === "rail_nas" ? "nas" : "services"].map((x) => x.id);
}

const reorder = (list, from, to) => save("/api/settings/order", { list, ids: moveItem(orderIds(list), from, to) });

async function fireArmed(key) {
  armed = null;
  if (key.startsWith("pk-")) {
    const r = await post(`/api/passkeys/${encodeURIComponent(key.slice(3))}/remove`);
    if (r.ok) toast("Passkey removed.");
    else if (r.status !== 401) toast(r.data.error || "Couldn't remove the passkey.", true);
    await loadPasskeys();
    render();
  } else if (key === "logout-all") {
    const r = await post("/api/account/logout-everywhere");
    if (r.ok) location.href = "/";
    else if (r.status !== 401) { toast(r.data.error || "That couldn't be saved.", true); render(); }
  } else {
    await save(`/api/settings/feeds/${encodeURIComponent(key.slice(3))}/remove`);
  }
}

const ACTIONS = {
  "feed-on": (b) => save(`/api/settings/feeds/${encodeURIComponent(b.dataset.id)}`, { enabled: b.getAttribute("aria-checked") !== "true" }),
  arm: (b) => {
    const key = b.dataset.key;
    if (armed === key) return fireArmed(key);
    armed = key;                 // first click only asks
    render();
    return undefined;
  },
  push: (b) => save("/api/settings/alerts", { push: b.getAttribute("aria-checked") !== "true" }),
  step: (b) => save("/api/settings/alerts", { [b.dataset.k]: Number(b.dataset.v) }),
  tab: (b) => { tab = b.dataset.tab; render(); },
  move: (b) => { const i = orderIds(b.dataset.list).indexOf(b.dataset.id); return reorder(b.dataset.list, i, Number(b.dataset.to)); },
  show: (b) => save("/api/settings/show", { list: b.dataset.list, id: b.dataset.id, show: b.getAttribute("aria-checked") !== "true" }),
  "dock-on": (b) => save(`/api/settings/services/${encodeURIComponent(b.dataset.id)}`, { on_dock: b.getAttribute("aria-checked") !== "true" }),
  ignore: (b) => save(`/api/settings/services/${encodeURIComponent(b.dataset.id)}/ignore`),
  remove: (b) => save(`/api/settings/services/${encodeURIComponent(b.dataset.id)}/remove`),
};

$("nav").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  section = b.dataset.s;
  armed = null;
  history.replaceState(null, "", `#${section}`);
  render();
  if (section === "account") loadPasskeys().then(render);
});

pane.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b || b.disabled) return;
  if (armed && b.dataset.act !== "arm") { armed = null; }
  ACTIONS[b.dataset.act]?.(b);
});

// Names and typed ports save when the field is left
pane.addEventListener("change", (e) => {
  const el = e.target;
  const url = `/api/settings/services/${encodeURIComponent(el.dataset.id)}`;
  if (el.dataset.act === "name") save(url, { name: el.value });
  if (el.dataset.act === "scheme") save(url, { scheme: el.value });
  if (el.dataset.act === "port") {
    if (el.value === "") save(url, { port: null });
    else if (/^\d+$/.test(el.value)) save(url, { port: Number(el.value) });
    else { toast("A port is a number from 1 to 65535.", true); render(); }
  }
});

pane.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (e.target.id === "add-feed") {
    const button = $("f-add");
    button.disabled = true;
    button.textContent = "Checking…";   // the NAS test-fetches the feed first
    const url = $("f-url").value;
    const ok = await save("/api/settings/feeds", { url, topic: $("f-topic").value, lang: $("f-lang").value });
    if (ok) toast("Feed added.");
    else $("f-url").value = url;
  } else if (e.target.id === "add-passkey") {
    await addPasskey();
  } else if (e.target.id === "change-pw") {
    await changePassword();
  }
});

async function addPasskey() {
  const name = $("pk-name").value.trim();
  if (!name) return toast("Give the passkey a name first, like iPhone.", true);
  $("pk-add").disabled = true;
  try {
    const opts = await post("/api/passkeys/options");
    if (!opts.ok) return opts.status === 401 ? undefined : toast(opts.data.error || "Couldn't add the passkey.", true);
    const cred = await navigator.credentials.create({ publicKey: toCreateOptions(opts.data.publicKey) });
    const r = await post("/api/passkeys", {
      name,
      clientDataJSON: bufToB64url(cred.response.clientDataJSON),
      attestationObject: bufToB64url(cred.response.attestationObject),
    });
    if (r.ok) toast("Passkey added.");
    else if (r.status !== 401) toast(r.data.error || "Couldn't add the passkey.", true);
    if (r.ok) { await loadPasskeys(); render(); }
  } catch (e) {
    if (e?.name !== "NotAllowedError") toast("Couldn't add the passkey.", true);   // a cancelled prompt stays quiet
  } finally {
    if ($("pk-add")) $("pk-add").disabled = false;
  }
  return undefined;
}

async function changePassword() {
  const current = $("pw-current").value, next = $("pw-new").value;
  if (next !== $("pw-again").value) return toast("The two new passwords don't match.", true);
  $("pw-save").disabled = true;
  const r = await post("/api/account/password", { current, new: next });
  $("pw-save").disabled = false;
  if (r.ok) {
    clearPasswords();
    return toast("Password changed.");
  }
  if (r.status === 401) return undefined;
  if (r.status === 403) return toast("That's not your current password.", true);
  if (r.status === 429) return toast(`Too many tries. Wait ${r.data.retry_after} seconds.`, true);
  return toast(r.data.error || "The password wasn't changed.", true);
}

function clearPasswords() {
  for (const id of ["pw-current", "pw-new", "pw-again"]) $(id).value = "";
}

// ---------- drag to reorder (the arrows do the same for touch and keyboard) ----------
let drag = null;
pane.addEventListener("dragstart", (e) => {
  const r = e.target.closest?.(".row[draggable]");
  if (!r) return;
  drag = { list: r.dataset.list, from: Number(r.dataset.index) };
  r.classList.add("dragging");
});
pane.addEventListener("dragover", (e) => {
  if (drag && e.target.closest?.(`.row[data-list="${drag.list}"]`)) e.preventDefault();
});
pane.addEventListener("drop", (e) => {
  const r = e.target.closest?.(`.row[data-list="${drag?.list}"]`);
  if (!r) return;
  e.preventDefault();
  const { list, from } = drag;
  drag = null;
  reorder(list, from, Number(r.dataset.index));
});
pane.addEventListener("dragend", () => { drag = null; render(); });

// ---------- header ----------
$("mission").href = at(8800);
$("logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  location.href = "/";
});

// ---------- start ----------
(async () => {
  if (!(await load())) { pane.innerHTML = `<p class="sub">Couldn't load the settings. Reload to try again.</p>`; return; }
  render();
  if (section === "account") loadPasskeys().then(render);
})();
// Pick up new containers while the page is open, but never redraw under someone who is typing
setInterval(async () => {
  const typing = ["INPUT", "SELECT"].includes(document.activeElement?.tagName);
  if (document.hidden || typing || section !== "services") return;
  if (await load()) render();
}, 30000);
