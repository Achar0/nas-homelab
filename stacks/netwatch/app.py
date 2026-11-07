"""Netwatch: where the NAS's network connections come from.

Every few seconds it reads the host's TCP table (/proc/net/tcp*; the container
runs with host networking), geolocates internet addresses with the offline
DB-IP Lite database, checks them against public attacker blocklists and keeps
24 h of history. A small JSON API + static page are served on PORT.
"""
import bisect
import datetime as dt
import gzip
import ipaddress
import json
import os
import shutil
import struct
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import maxminddb

import auth

PORT = int(os.environ.get("PORT", "8790"))
DATA = os.environ.get("DATA_DIR", "/data")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
HOME = (float(os.environ.get("HOME_LAT", "45.46")), float(os.environ.get("HOME_LON", "9.19")))
TORRENT_PORT = int(os.environ.get("TORRENT_PORT", "6888"))
HOME_URL = os.environ.get("HOME_URL", "http://127.0.0.1:3001")
NTFY_URL = os.environ.get("NTFY_URL", "")  # e.g. https://ntfy.sh/<topic>; empty = no phone alerts
POLL_S = 5
HISTORY_S = 24 * 3600
UA = {"User-Agent": "netwatch-nas/1.0"}
LOOPBACK = {"127.0.0.1", "::1"}   # Home and Mission Control read /api/state from this machine, no reverse proxy

# Known services: local listening ports (inbound) and common remote ports (outbound)
LOCAL_SERVICES = {22: "SSH", 53: "DNS", 80: "UGOS", 443: "UGOS", 445: "SMB", 9443: "UGOS",
                  9999: "UGOS", 6888: "qBittorrent", 8888: "qBittorrent", 25565: "Minecraft",
                  8080: "AdGuard", 3001: "Home", 5001: "Dockge", 3002: "Uptime Kuma",
                  7892: "AutoBangumi", 8765: "Speedtest", 61208: "Glances",
                  8800: "Mission Control"}
REMOTE_SERVICES = {443: "HTTPS", 80: "HTTP", 53: "DNS", 853: "DNS over TLS", 123: "Time",
                   993: "Mail", 22: "SSH"}
BLOCKLISTS = {
    "FireHOL level 1": "https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level1.netset",
    "blocklist.de (reported attackers)": "https://lists.blocklist.de/lists/all.txt",
}
VENDOR = {
    "d3.min.js": "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js",
    "topojson-client.min.js": "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js",
    "countries-110m.json": "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json",
}

lock = threading.Lock()
state = {"history": {}, "current": [], "updated": 0, "lists_updated": 0, "geo_db": ""}
geo = None
ranges = {}  # list name -> (sorted starts, ends) for IPv4/IPv6 ints


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def download(url, dest):
    tmp = dest + ".part"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)


# ---------- GeoIP (DB-IP City Lite, monthly, CC BY 4.0) ----------
def ensure_geoip():
    global geo
    today = dt.date.today()
    months = [today.strftime("%Y-%m"), (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")]
    for m in months:
        path = os.path.join(DATA, f"dbip-city-lite-{m}.mmdb")
        if not os.path.exists(path):
            try:
                log("downloading GeoIP", m)
                download(f"https://download.db-ip.com/free/dbip-city-lite-{m}.mmdb.gz", path + ".gz")
                with gzip.open(path + ".gz") as src, open(path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.remove(path + ".gz")
            except Exception as e:
                log("GeoIP", m, "not available:", e)
                continue
        geo = maxminddb.open_database(path)
        state["geo_db"] = m
        for old in os.listdir(DATA):  # keep only the database in use
            if old.startswith("dbip-city-lite-") and old != os.path.basename(path):
                os.remove(os.path.join(DATA, old))
        return
    log("no GeoIP database available yet")


def locate(ip):
    if not geo:
        return None
    r = geo.get(ip) or {}
    loc = r.get("location") or {}
    if "latitude" not in loc:
        return None
    return {"lat": loc["latitude"], "lon": loc["longitude"],
            "city": ((r.get("city") or {}).get("names") or {}).get("en", ""),
            "country": ((r.get("country") or {}).get("names") or {}).get("en", ""),
            "cc": (r.get("country") or {}).get("iso_code", "")}


# ---------- Attacker blocklists ----------
def load_blocklists():
    new = {}
    for name, url in BLOCKLISTS.items():
        path = os.path.join(DATA, "list-" + url.rsplit("/", 1)[-1])
        try:
            fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < 12 * 3600
            if not fresh:
                download(url, path)
        except Exception as e:
            log("blocklist", name, "download failed:", e)
            if not os.path.exists(path):
                continue
        spans = []
        for line in open(path, encoding="utf-8", errors="ignore"):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                net = ipaddress.ip_network(line, strict=False)
            except ValueError:
                continue
            if not net.is_global:  # FireHOL level 1 includes private/bogon ranges: ignore them
                continue
            spans.append((int(net.network_address), int(net.broadcast_address), net.version))
        spans.sort()
        new[name] = ([s[0] for s in spans], spans)
        log("blocklist", name, len(spans), "entries")
    if new:
        ranges.clear()
        ranges.update(new)
        state["lists_updated"] = time.time()


def blocklisted(ip):
    n, v = int(ip), ip.version
    hits = []
    for name, (starts, spans) in ranges.items():
        i = bisect.bisect_right(starts, n) - 1
        # walk back a little: overlapping CIDRs may start earlier and still cover n
        for j in range(i, max(i - 8, -1), -1):
            s, e, ver = spans[j]
            if ver == v and s <= n <= e:
                hits.append(name)
                break
    return hits


# ---------- Connection table ----------
def parse_proc(path, v6):
    try:
        lines = open(path).read().splitlines()[1:]
    except OSError:
        return
    for line in lines:
        p = line.split()
        (lip, lport), (rip, rport), st = p[1].split(":"), p[2].split(":"), p[3]

        def addr(h):
            if v6:
                b = bytes.fromhex(h)
                b = b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4))
                a = ipaddress.IPv6Address(b)
                return a.ipv4_mapped or a
            return ipaddress.IPv4Address(struct.pack("<I", int(h, 16)))
        yield addr(lip), int(lport, 16), addr(rip), int(rport, 16), st


def scope(ip):
    if ip in ipaddress.ip_network("100.64.0.0/10"):
        return "tailscale"
    if ip.is_global:
        return "internet"
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return None
    return "lan"


def poll():
    listening, conns = set(), []
    for path, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        for lip, lport, rip, rport, st in parse_proc(path, v6):
            if st == "0A":
                listening.add((lip, lport))
            elif st == "01":  # ESTABLISHED
                conns.append((lip, lport, rip, rport))
    now = time.time()
    current = []
    for lip, lport, rip, rport in conns:
        sc = scope(rip)
        if sc is None or str(rip).startswith("172.17.") or str(rip).startswith("172.18."):
            continue  # skip loopback and container-to-container traffic
        # Inbound only if something listens on this exact address (or a wildcard) and port:
        # an outgoing socket can reuse a port another app listens on elsewhere (e.g. Tailscale)
        inbound = any(p == lport and (a == lip or a.is_unspecified) for a, p in listening)
        port = lport if inbound else rport
        if inbound:
            service = LOCAL_SERVICES.get(lport, f"port {lport}")
        else:
            service = REMOTE_SERVICES.get(rport, "Torrent peer" if rport > 1024 else f"port {rport}")
        reasons = []
        if sc == "internet":
            reasons += blocklisted(rip)
            if inbound and lport != TORRENT_PORT:
                reasons.append(f"Inbound from the internet to {service}")
        current.append({"ip": str(rip), "scope": sc, "dir": "in" if inbound else "out",
                        "port": port, "service": service, "flag": reasons})
    with lock:
        hist = state["history"]
        for c in current:
            h = hist.get(c["ip"])
            if not h:
                h = hist[c["ip"]] = {"ip": c["ip"], "scope": c["scope"], "first": now, "count": 0,
                                     "services": [], "dir": c["dir"], "flag": [],
                                     "geo": locate(ipaddress.ip_address(c["ip"])) if c["scope"] == "internet" else None}
            h["last"] = now
            h["count"] += 1
            if c["service"] not in h["services"]:
                h["services"] = (h["services"] + [c["service"]])[-4:]
            if c["dir"] == "in":
                h["dir"] = "in"
            h["flag"] = sorted(set(h["flag"]) | set(c["flag"]))
        for ip in [ip for ip, h in hist.items() if now - h["last"] > HISTORY_S]:
            del hist[ip]
        state["current"] = current
        state["updated"] = now
        # Newly flagged addresses: alert once per address while it stays in the 24 h history
        fresh = [h for h in hist.values() if h["flag"] and not h.get("alerted")]
        for h in fresh:
            h["alerted"] = True
        fresh = [dict(h) for h in fresh]
    if fresh:
        threading.Thread(target=send_alerts, args=(fresh,), daemon=True).start()


# ---------- Phone alerts (ntfy) ----------
alert_times = []  # timestamps of sent alerts, for the hourly cap


def push_enabled():
    """The phone switch in Home's Settings. If Home can't say, keep alerting."""
    try:
        with urllib.request.urlopen(HOME_URL + "/api/internal/layout", timeout=2) as r:
            return json.load(r).get("push", True) is not False
    except Exception:  # noqa: BLE001 - whatever went wrong, an alert must not be lost
        return True


def send_alerts(items):
    """One ntfy notification per poll listing the new red flags; max 10 per hour."""
    if not NTFY_URL or not push_enabled():
        return
    now = time.time()
    alert_times[:] = [t for t in alert_times if now - t < 3600]
    if len(alert_times) >= 10:
        log("alert cap reached, skipped", len(items), "flag(s)")
        return
    lines = []
    for h in items[:5]:
        g = h.get("geo") or {}
        where = ", ".join(x for x in (g.get("city"), g.get("country")) if x) or "unknown location"
        lines.append(f"{h['ip']} ({where}) · {', '.join(h['services'])}\n  {' · '.join(h['flag'])}")
    if len(items) > 5:
        lines.append(f"…and {len(items) - 5} more")
    title = "Netwatch: flagged connection" if len(items) == 1 else f"Netwatch: {len(items)} flagged connections"
    req = urllib.request.Request(NTFY_URL, data="\n".join(lines).encode(), headers={
        **UA, "Title": title, "Priority": "high", "Tags": "rotating_light",
        "Click": "http://192.168.1.14:8790"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        alert_times.append(now)
        log("alert sent:", title)
    except Exception as e:
        log("alert failed:", e)


def snapshot():
    with lock:
        live = {c["ip"] for c in state["current"]}
        items = []
        for h in state["history"].values():
            d = dict(h)
            d["live"] = h["ip"] in live
            items.append(d)
    items.sort(key=lambda h: (not h["flag"], not h["live"], -h["last"]))
    internet = [h for h in items if h["scope"] == "internet"]
    countries = {}
    for h in internet:
        if h.get("geo") and h["geo"]["country"]:
            countries[h["geo"]["country"]] = countries.get(h["geo"]["country"], 0) + 1
    return {
        "updated": state["updated"], "home": {"lat": HOME[0], "lon": HOME[1]},
        "lists_updated": state["lists_updated"], "geo_db": state["geo_db"],
        "lists": list(ranges.keys()),
        "summary": {
            "live": len(state["current"]),
            "live_internet": sum(1 for h in internet if h["live"]),
            "internet_24h": len(internet),
            "lan_24h": sum(1 for h in items if h["scope"] == "lan"),
            "tailscale_24h": sum(1 for h in items if h["scope"] == "tailscale"),
            "flagged_24h": sum(1 for h in items if h["flag"]),
            "countries": sorted(countries.items(), key=lambda kv: -kv[1])[:6],
        },
        "items": items[:400],
    }


def save_history():
    with lock:
        data = json.dumps(state["history"])
    with open(os.path.join(DATA, "history.json.part"), "w") as f:
        f.write(data)
    os.replace(os.path.join(DATA, "history.json.part"), os.path.join(DATA, "history.json"))


def worker():
    last_save = last_lists = last_geo = 0
    while True:
        try:
            now = time.time()
            if now - last_geo > 24 * 3600:
                ensure_geoip()
                last_geo = now
            if now - last_lists > 12 * 3600:
                load_blocklists()
                last_lists = now
            poll()
            if now - last_save > 60:
                save_history()
                last_save = now
        except Exception as e:
            log("poll error:", repr(e))
        time.sleep(POLL_S)


def ensure_vendor():
    os.makedirs(os.path.join(DATA, "vendor"), exist_ok=True)
    for name, url in VENDOR.items():
        p = os.path.join(DATA, "vendor", name)
        if not os.path.exists(p):
            try:
                download(url, p)
            except Exception as e:
                log("vendor", name, "failed:", e)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def allowed(self):
        return self.client_address[0] in LOOPBACK or auth.require_login(self)

    def do_HEAD(self):
        if self.allowed():
            super().do_HEAD()

    def do_GET(self):
        if not self.allowed():   # every path: page, vendor files and data
            return
        if self.path.startswith("/api/state"):
            body = json.dumps(snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/vendor/"):
            name = os.path.basename(self.path.split("?")[0])
            p = os.path.join(DATA, "vendor", name)
            if name not in VENDOR or not os.path.exists(p):
                self.send_error(404)
                return
            body = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if name.endswith(".json") else "text/javascript")
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    auth.startup_check(log)
    os.makedirs(DATA, exist_ok=True)
    try:
        state["history"] = json.load(open(os.path.join(DATA, "history.json")))
    except Exception:
        pass
    ensure_vendor()
    threading.Thread(target=worker, daemon=True).start()
    log("netwatch on port", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
