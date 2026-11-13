// Public page for family and guests: status, news, downloads, UGOS link and the admin login.
import { esc, formatAgo, greeting, fmtTB, fmtMbps, otherLabel } from "./lib.js";
import { mountNews } from "./news.js";
import { bufToB64url, toGetOptions, passkeysAvailable } from "./passkey.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const demo = params.get("demo");

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

function renderHello() {
  const d = new Date();
  $("hello").textContent = greeting(d.getHours());
  $("today").textContent = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }) +
    " · " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function renderStatus(s) {
  $("state").className = `g-state ${s.state}`;
  $("s-title").textContent = s.title;
  $("s-detail").textContent = s.detail;
}

function renderDownloads(d) {
  const label = (x) => esc(`${x.show} · ${x.ep}`);
  const done = d.arrived.map((a) => `<div class="ep"><b>${label(a)}</b><span>Arrived ${esc(formatAgo(a.at))}</span></div>`);
  const active = d.downloading.map((x) => `<div class="ep ${x.stalled ? "stalled" : ""}"><b>${label(x)}</b>
    <span>${Math.floor(x.progress * 100)}%${x.stalled ? " · stalled" : x.eta ? ` · about ${Math.ceil(x.eta / 60)} min left` : ""}</span>
    <div class="bar"><i style="width:${(x.progress * 100).toFixed(1)}%"></i></div></div>`);
  const other = otherLabel(d.other);
  const cards = [...done, ...active, ...(other ? [`<div class="ep none">${esc(other)}</div>`] : [])];
  $("eps").innerHTML = cards.join("") || `<div class="ep none">Nothing new in the last 48 h</div>`;
}

async function refreshSummary() {
  try {
    const d = await getJSON(`/api/public/summary${demo ? `?demo=${encodeURIComponent(demo)}` : ""}`);
    renderStatus(d.status);
    $("internet").textContent = fmtMbps(d.internet_bps);
    $("free").textContent = fmtTB(d.free_bytes);
    renderDownloads(d.downloads);
  } catch {
    renderStatus({ state: "unknown", title: "Status unavailable", detail: "" });
  }
}

// ---------- login ----------
const login = $("login");
let conditional = null;   // AbortController of the autofill passkey prompt, if one is waiting

async function startConditional() {
  if ($("l-passkey").hidden) return;   // no secure context: nothing to offer
  if (!(await window.PublicKeyCredential?.isConditionalMediationAvailable?.())) return;
  conditional = new AbortController();
  const mine = conditional;
  try {
    const options = await passkeyOptions();
    const cred = await navigator.credentials.get({ publicKey: toGetOptions(options), mediation: "conditional", signal: mine.signal });
    await finishPasskeyLogin(cred);
  } catch (e) {
    // Aborted, cancelled or unsupported: the password form still works.
    // A refused sign-in says so and asks again (a fresh challenge) while the dialog is open.
    if (e?.rejected && conditional === mine && login.open) {
      $("l-error").textContent = "That passkey didn't work. Use your password.";
      conditional = null;
      startConditional();
      return;
    }
  }
  if (conditional === mine) conditional = null;
}

async function passkeyOptions() {
  const r = await fetch("/api/passkey/login/options", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  if (!r.ok) throw new Error("options");
  return (await r.json()).publicKey;
}

// Sends the signed challenge; goes to `next` when the NAS accepts it
async function finishPasskeyLogin(cred) {
  const resp = cred.response;
  const r = await fetch("/api/passkey/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: cred.id,
      clientDataJSON: bufToB64url(resp.clientDataJSON),
      authenticatorData: bufToB64url(resp.authenticatorData),
      signature: bufToB64url(resp.signature),
      remember: $("l-remember").checked,
      next: params.get("next"),
    }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error || "login"), { rejected: true });
  location.href = d.next;
}

$("l-passkey").addEventListener("click", async () => {
  conditional?.abort();
  conditional = null;
  $("l-passkey").disabled = true;
  $("l-error").textContent = "";
  try {
    const cred = await navigator.credentials.get({ publicKey: toGetOptions(await passkeyOptions()) });
    await finishPasskeyLogin(cred);
  } catch (e) {
    if (e?.name !== "NotAllowedError") $("l-error").textContent = "That passkey didn't work. Use your password.";
  } finally {
    $("l-passkey").disabled = false;
    if (login.open) startConditional();
  }
});

login.addEventListener("close", () => { conditional?.abort(); conditional = null; });

function openLogin() {
  $("l-error").textContent = "";
  login.showModal();
  $("l-pw").focus();
  if (!conditional) startConditional();
}

passkeysAvailable().then((ok) => {
  $("l-passkey").hidden = $("l-or").hidden = !ok;
  if (ok && login.open && !conditional) startConditional();   // ?login=1 opened the dialog first
});
$("admin").addEventListener("click", openLogin);
$("l-cancel").addEventListener("click", () => login.close());

const ERRORS = {
  wrong: () => "Wrong password",
  wait: (d) => `Too many tries. Try again in ${d.retry_after} s`,
  not_configured: () => "Login isn't set up yet",
};
$("l-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("l-submit").disabled = true;
  $("l-error").textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pw: $("l-pw").value, remember: $("l-remember").checked, next: params.get("next") }),
    });
    const d = await r.json();
    if (r.ok) { location.href = d.next; return; }
    $("l-error").textContent = (ERRORS[d.error] || (() => "Couldn't log in. Try again."))(d);
    $("l-pw").select();
  } catch {
    $("l-error").textContent = "Couldn't reach the NAS. Try again.";
  } finally {
    $("l-submit").disabled = false;
  }
});

// ---------- start ----------
$("ugos").href = `https://${location.hostname}:9443/`;
const news = mountNews({
  getJSON,
  topics: { all: "All", tech: "Tech", markets: "Markets", discoveries: "Discoveries" },
  keysBlocked: () => login.open,
});
renderHello();
refreshSummary();
news.start();
if (params.has("login")) openLogin();

const every = (ms, fn) => setInterval(() => { if (!document.hidden) fn(); }, ms);
every(30000, refreshSummary);
every(30000, renderHello);
every(300000, () => news.refresh(true));
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshSummary(); });
