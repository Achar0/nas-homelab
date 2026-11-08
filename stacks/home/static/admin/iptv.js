// IPTV lists: status, channels, add and remove. Outside text only goes in through textContent.
const $ = (id) => document.getElementById(id);
const FILE_LIMIT = 5_000_000;
const STATES = ["online", "lag", "offline"];
const open = new Set();      // lists showing their channels
let confirming = null;       // list waiting for the second press on Remove

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function say(text) { $("msg").textContent = text; }

async function post(path, body = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) location.href = "/?login=1";
  if (!r.ok) throw new Error(data.error || "That didn't work");
  return data;
}

const when = (t) => (t ? new Date(t * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "not checked yet");
const line = (c) => `${c.online} online · ${c.lag} lag · ${c.offline} offline`;

async function showChannels(box, id, filter) {
  const r = await fetch(`/api/iptv/channels?id=${encodeURIComponent(id)}`);
  if (!r.ok) return;
  const { channels } = await r.json();
  const rows = channels.filter((c) => filter === "all" || c.state === filter);
  box.replaceChildren(...rows.map((c) => {
    const row = el("div", "chan");
    row.title = c.url;
    row.append(el("b", "", c.group ? `${c.name} · ${c.group}` : c.name), el("span", c.state, c.state));
    return row;
  }));
  if (!rows.length) box.replaceChildren(el("p", "sub", "None"));
}

function drawList(lst) {
  const row = el("div", "list");
  row.append(el("h2", "", lst.name));
  const kind = lst.kind === "file" ? "uploaded file" : lst.url;
  row.append(el("p", "sub", `${lst.counts.total ? line(lst.counts) : "Waiting for its first check"} · ${when(lst.checked)}`));
  row.append(Object.assign(el("p", "sub", kind), { style: "overflow-wrap:anywhere" }));
  if (lst.error) row.append(el("p", "sub err", "The last check couldn't read this list; these are its previous results."));

  const acts = el("div", "acts");
  const chans = el("div", "chans");
  chans.hidden = !open.has(lst.id);
  const toggle = el("button", "", open.has(lst.id) ? "Hide channels" : "Channels");
  toggle.onclick = () => {
    if (open.has(lst.id)) open.delete(lst.id); else open.add(lst.id);
    refresh();
  };
  acts.append(toggle);
  if (open.has(lst.id)) {
    for (const f of ["all", ...STATES]) {
      const b = el("button", "", f);
      b.onclick = () => showChannels(chans, lst.id, f);
      acts.append(b);
    }
    showChannels(chans, lst.id, "all");
  }
  const remove = el("button", confirming === lst.id ? "danger" : "", confirming === lst.id ? "Press again to remove" : "Remove");
  remove.onclick = async () => {
    if (confirming !== lst.id) { confirming = lst.id; return refresh(); }
    confirming = null;
    try { await post(`/api/iptv/lists/${encodeURIComponent(lst.id)}/delete`); say("Removed"); } catch (e) { say(e.message); }
    refresh();
  };
  acts.append(remove);
  row.append(acts, chans);
  return row;
}

let timer = null;

async function refresh() {
  clearTimeout(timer);
  const r = await fetch("/api/iptv").catch(() => null);
  if (!r || !r.ok) { say("Can't reach the NAS"); timer = setTimeout(refresh, 15000); return; }
  const d = await r.json();
  $("total").textContent = d.counts ? `${d.counts.online} / ${d.counts.total}` : "—";
  $("detail").textContent = d.checking ? "Checking now… this can take about 10 minutes"
    : d.counts ? `${line(d.counts)} · checked ${when(d.checked)}` : "No check yet";
  $("check").disabled = d.checking;
  $("lists").replaceChildren(...(d.lists.length ? d.lists.map(drawList) : [el("p", "sub list", "No lists yet: add one below.")]));
  timer = setTimeout(refresh, d.checking ? 5000 : 60000);
}

$("check").onclick = async () => {
  try { await post("/api/iptv/check"); say("Checking started"); } catch (e) { say(e.message); }
  setTimeout(refresh, 800);
};

$("add").onsubmit = async (ev) => {
  ev.preventDefault();
  try {
    await post("/api/iptv/lists", { url: $("url").value.trim(), name: $("name").value.trim() });
    $("url").value = ""; $("name").value = "";
    say("Added: its channels will be checked now");
  } catch (e) { say(e.message); }
  setTimeout(refresh, 800);
};

$("file").onchange = async () => {
  const file = $("file").files[0];
  $("file").value = "";
  if (!file) return;
  if (file.size > FILE_LIMIT) return say("That file is larger than 5 MB");
  try {
    await post("/api/iptv/upload", { name: $("name").value.trim() || file.name, content: await file.text() });
    $("name").value = "";
    say("Uploaded: its channels will be checked now");
  } catch (e) { say(e.message); }
  setTimeout(refresh, 800);
};

refresh();
