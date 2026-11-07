"""Home: the NAS landing page (:3001).

Serves static/ and a small API, and runs three background workers:
  feeds      every 15 min  -> /api/news
  attention  every 30 s    -> /api/attention (+ ntfy push for new urgent incidents)
  arrivals   every 60 s    -> /api/arrivals
State that must survive restarts (incidents, dismissals, acknowledgements) is in DATA/state.json.
The only writes are POST /api/attention/<id>/{dismiss,ack}, which change that file and nothing else.

/ is the public guest page and /api/public/summary its data. The owner's page (static/admin/) and
every API that isn't explicitly public need the admin login, see auth.py.
"""
import base64
import http.cookiejar
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import arrivals
import attention
import auth
import feeds
import guest
import news_db

E = os.environ.get
PORT = int(E("PORT", "3001"))
DATA = E("DATA_DIR", "/data")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
STATE_PATH = os.path.join(DATA, "state.json")
NEWS_DB = os.path.join(DATA, "news.db")   # archive: every story shown (30 days), opened ones (90 days)
PROM = E("PROM_URL", "http://127.0.0.1:9090")
NETWATCH = E("NETWATCH_URL", "http://127.0.0.1:8790")
DOCKER = E("DOCKER_URL", "http://127.0.0.1:2375")
QBT = E("QBT_URL", "http://127.0.0.1:8888")
KUMA = E("KUMA_URL", "http://127.0.0.1:3002")
NTFY_URL = E("NTFY_URL", "")
UA = {"User-Agent": "nas-home/1.0 (personal feed reader)"}

ADMIN_STATIC = os.path.join(STATIC, "admin")
LOGIN_BODY_LIMIT = 4096
THROTTLE = auth.Throttle()
login_lock = threading.Lock()   # one password check at a time: scrypt is deliberately expensive
lock = threading.Lock()
STATE = {}
LATEST = {"attention": {"items": [], "urgent": None, "sources_down": []}, "news": [], "news_errors": [],
          "news_updated": 0, "arrivals": {"arrived": [], "downloading": []}, "inputs": None, "inputs_at": 0}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------- state file ----------
def load_state():
    try:
        with open(STATE_PATH) as f:
            STATE.update(json.load(f))
    except (OSError, ValueError):
        pass


def save_state():
    os.makedirs(DATA, exist_ok=True)
    tmp = STATE_PATH + ".part"
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, STATE_PATH)


# ---------- inputs ----------
def get(url, headers=None, timeout=10, opener=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
        return r.read()


FEED_LIMIT = 5_000_000   # bytes: a feed bigger than this is junk
FEED_DEADLINE = 10       # seconds for the whole download, not per read (a trickling server can't stall us)


def get_limited(url, limit=FEED_LIMIT, deadline=FEED_DEADLINE):
    start, chunks, size = time.monotonic(), [], 0
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=min(deadline, 10)) as r:
        while True:
            if time.monotonic() - start > deadline:
                raise TimeoutError(f"{url}: slower than {deadline} s")
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > limit:
                raise ValueError(f"{url}: larger than {limit} bytes")
            chunks.append(chunk)


def prom_vector(query):
    d = json.loads(get(PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": query})))
    return d["data"]["result"]


def prom_one(query):
    r = prom_vector(query)
    return float(r[0]["value"][1]) if r else None


def prom_by(query, label):
    return {x["metric"].get(label, ""): float(x["value"][1]) for x in prom_vector(query)}


def read_prom():
    return {
        "md_active": prom_one('node_md_disks{device="md1",state="active"}'),
        "md_required": prom_one('node_md_disks_required{device="md1"}'),
        "smart_status": prom_by("smartctl_device_smart_status", "device"),
        "drive_temp": prom_by('smartctl_device_temperature{temperature_type="current"}', "device"),
        "free_ratio": prom_one('node_filesystem_avail_bytes{mountpoint="/volume1"} / node_filesystem_size_bytes{mountpoint="/volume1"}'),
        "free_bytes": prom_one('node_filesystem_avail_bytes{mountpoint="/volume1"}'),
        "speed_last": prom_one("mc_speedtest_download_bits_per_second"),
        "speed_median": prom_one("quantile_over_time(0.5, mc_speedtest_download_bits_per_second[30d])"),
    }


def read_kuma():
    key = E("KUMA_API_KEY", "")
    if not key:
        return None   # not configured: rule skipped, reported in sources_down
    auth = base64.b64encode(f":{key}".encode()).decode()
    out = {}
    for line in get(KUMA + "/metrics", {"Authorization": "Basic " + auth}).decode().splitlines():
        if line.startswith("monitor_status{"):
            labels, value = line.rsplit(" ", 1)
            name = labels.split('monitor_name="', 1)[1].split('"', 1)[0]
            out[name] = int(float(value))   # 1 up, 0 down, 2 pending, 3 maintenance
    return out


_restart_samples = {}   # container -> [(t, RestartCount)]


def read_restarts(now):
    out = {}
    for c in json.loads(get(DOCKER + "/containers/json?all=1")):
        name = c["Names"][0].lstrip("/")
        count = json.loads(get(f"{DOCKER}/containers/{c['Id']}/json")).get("RestartCount", 0)
        hist = [s for s in _restart_samples.get(name, []) if now - s[0] <= 600] + [(now, count)]
        _restart_samples[name] = hist
        out[name] = count - hist[0][1]
    return out


class Qbt:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("Referer", QBT)]

    def torrents(self):
        try:
            return json.loads(get(QBT + "/api/v2/torrents/info", opener=self.op))
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            body = urllib.parse.urlencode({"username": E("QBT_USER", ""), "password": E("QBT_PASS", "")}).encode()
            self.op.open(QBT + "/api/v2/auth/login", body, timeout=10)
            return json.loads(get(QBT + "/api/v2/torrents/info", opener=self.op))


qbt = Qbt()


def send_push(title, detail):
    if not NTFY_URL:
        return
    req = urllib.request.Request(NTFY_URL, data=detail.encode(), method="POST",
                                 headers={"Title": f"URGENT: {title}", "Priority": "urgent", "Tags": "rotating_light"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except OSError as e:
        log("push failed:", e)


# ---------- workers ----------
def gather_inputs(now):
    inputs, down = {"ab_missing": None}, []
    for key, read in (("netwatch", lambda: json.loads(get(NETWATCH + "/api/state"))), ("kuma", read_kuma),
                      ("prom", read_prom), ("restarts", lambda: read_restarts(now))):
        try:
            inputs[key] = read()
        except Exception as e:  # noqa: BLE001 - a source being down must not stop the others
            inputs[key] = None
            log(key, "unavailable:", e)
        if inputs[key] is None:
            down.append(key)
    return inputs, down


def attention_tick(gather=gather_inputs):
    now = time.time()
    inputs, down = gather(now)
    with lock:
        items, urgent, pushes = attention.evaluate(inputs, STATE, now)
        LATEST["attention"] = {"items": items, "urgent": urgent, "sources_down": down}
        LATEST["inputs"], LATEST["inputs_at"] = inputs, now   # raw readings for the guest status line
        try:
            save_state()
        except OSError as e:   # e.g. disk full: keep showing and pushing, just log it
            log("state not saved:", e)
    for p in pushes:
        send_push(p["title"], p["detail"])


def feeds_tick():
    with open(os.path.join(HERE, "feeds.json")) as f:
        cfg = json.load(f)
    items, errors = feeds.fetch_all(cfg, get_limited)
    cutoff = time.time() - 3 * 86400
    LATEST["news"] = feeds.balance(feeds.dedupe([i for i in items if i["published"] > cutoff]))[:60]
    LATEST["news_errors"], LATEST["news_updated"] = errors, time.time()
    news_db.store(NEWS_DB, LATEST["news"], time.time())
    news_db.prune(NEWS_DB, time.time())
    if errors:
        log("feeds failed:", ", ".join(errors))


def arrivals_tick():
    LATEST["arrivals"] = arrivals.build(qbt.torrents(), time.time())


def loop(fn, every):
    while True:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - keep the worker alive
            log(fn.__name__, "failed:", e)
        time.sleep(every)


# ---------- HTTP ----------
def prom_target(path, qs):
    return f"{PROM}/api/v1/query?{qs}" if path == "/api/prom/query" else None


DEMO = {"id": "demo", "level": "urgent", "title": "Possible intrusion",
        "detail": "203.0.113.7 (Amsterdam, NL) · SSH · On blocklist.de (demo, nothing was sent)",
        "app": "netwatch", "since": 0, "resolved": False, "acked": False}
DEMO_MANY = [  # ?demo=many: preview several cards in priority order (never stored, never pushed)
    {**DEMO, "id": "demo-1", "since": time.time() - 200},
    {"id": "demo-2", "level": "urgent", "title": "AdGuard is down", "detail": "Uptime Kuma reports it unreachable (demo)",
     "app": "kuma", "since": time.time() - 900, "resolved": False, "acked": True},
    {"id": "demo-3", "level": "normal", "title": "Free space low", "detail": "12% free on the RAID volume (demo)",
     "app": "mission", "since": time.time() - 7200, "resolved": False, "acked": False},
    {"id": "demo-4", "level": "normal", "title": "Slow internet", "detail": "Last speed test 310 Mb/s, usually 930 Mb/s (demo)",
     "app": "speedtest", "since": time.time() - 3 * 3600, "resolved": True, "acked": False},
]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def json(self, obj, code=200, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def logged_in(self):
        return auth.session_ok(self.headers.get("Cookie"), time.time())

    def is_admin_file(self):
        """Judged on the resolved file, so /%61dmin/ or /x/../admin/ can't slip past."""
        resolved = self.translate_path(self.path)
        return resolved == ADMIN_STATIC or resolved.startswith(ADMIN_STATIC + os.sep)

    def do_HEAD(self):
        if self.is_admin_file() and not auth.require_login(self):
            return
        super().do_HEAD()

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        q = urllib.parse.parse_qs(qs)
        if path == "/":
            if self.logged_in():   # never back to ?next: another port just refused this cookie, it would loop
                return self.redirect(auth.DEFAULT_NEXT)
            return super().do_GET()
        if path == "/api/public/summary":
            data = guest.summary(LATEST["inputs"], LATEST["arrivals"], time.time(), LATEST["inputs_at"])
            demo = guest.DEMO.get((q.get("demo") or [""])[0])
            return self.json({**data, "status": demo} if demo else data)
        if path == "/api/news" and "opened" not in q.get("topic", []):
            topic = (q.get("topic") or ["all"])[0]
            items = [i for i in LATEST["news"] if topic == "all" or i["topic"] == topic]
            data = {"items": items, "updated": LATEST["news_updated"]}
            return self.json({**data, "errors": LATEST["news_errors"]} if self.logged_in() else data)
        if path.startswith("/api/"):
            if not auth.require_login(self):
                return None
        elif self.is_admin_file():
            if not auth.require_login(self):
                return None
            if self.translate_path(self.path) == ADMIN_STATIC and not path.endswith("/"):
                return self.redirect("/admin/")
        if path == "/api/attention":
            data = dict(LATEST["attention"])
            if q.get("demo") == ["urgent"]:   # preview the takeover; never stored, never pushed
                data = {**data, "items": [DEMO] + data["items"], "urgent": DEMO}
            elif q.get("demo") == ["many"]:
                data = {**data, "items": DEMO_MANY + data["items"], "urgent": None}
            return self.json(data)
        if path == "/api/news":   # stories whose link you opened, last 30 days, most recent first
            items = news_db.history(NEWS_DB, opened_only=True, since=time.time() - 30 * 86400)
            return self.json({"items": items, "updated": time.time(), "errors": []})
        if path == "/api/arrivals":
            return self.json(LATEST["arrivals"])
        if path.startswith("/api/prom/"):
            url = prom_target(path, qs)
            if not url:
                return self.send_error(404)
            try:
                return self.json(json.loads(get(url)))
            except OSError:
                return self.json({"error": "prometheus unavailable"}, 502)
        if path.startswith("/api/"):
            return self.send_error(404)
        return super().do_GET()

    def login(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length > LOGIN_BODY_LIMIT:
            self.close_connection = True   # the body stays unread
            return self.json({"error": "too big"}, 413)
        try:
            body = json.loads(self.rfile.read(length)) if length > 0 else None
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("pw"), str):
            return self.json({"error": "bad request"}, 400)
        if not auth.configured():
            log("login refused:", auth.auth_file(), "is missing or invalid")
            return self.json({"error": "not_configured"}, 503)
        addr, now = self.client_address[0], time.time()
        with login_lock:
            wait = THROTTLE.wait(addr, now)
            if wait:
                return self.json({"error": "wait", "retry_after": wait}, 429)
            if not auth.login_ok(body["pw"]):
                THROTTLE.fail(addr, now)
                return self.json({"error": "wrong"}, 401)
            THROTTLE.reset(addr)
        target = auth.safe_next(body.get("next"), auth.request_hostname(self))
        return self.json({"ok": True, "next": target}, cookie=auth.login_cookie(bool(body.get("remember")), now))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/login":
            return self.login()
        if path == "/api/logout":
            return self.json({"ok": True}, cookie=auth.logout_cookie())
        if not auth.require_login(self):
            return None
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "news"] and parts[3] == "open":
            ok = news_db.mark_opened(NEWS_DB, urllib.parse.unquote(parts[2]), time.time())
            return self.json({"ok": True}) if ok else self.send_error(404)
        if len(parts) == 4 and parts[:2] == ["api", "attention"] and parts[3] in ("dismiss", "ack"):
            cid = urllib.parse.unquote(parts[2])
            with lock:
                ok = (attention.dismiss if parts[3] == "dismiss" else attention.ack)(STATE, cid)
                if ok:
                    try:
                        save_state()
                    except OSError as e:
                        log("state not saved:", e)
                    items, urgent, _ = attention.evaluate({}, STATE, time.time())   # no inputs: only re-render
                    LATEST["attention"] = {**LATEST["attention"], "items": items, "urgent": urgent}
            return self.json({"ok": True}) if ok else self.send_error(404)
        return self.send_error(404)

    def end_headers(self):
        if not any(h.startswith(b"Cache-Control") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *a):
        pass


def make_server(port):
    os.makedirs(DATA, exist_ok=True)
    news_db.init(NEWS_DB)
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    load_state()
    auth.startup_check(log)
    for fn, every in ((attention_tick, 30), (feeds_tick, 900), (arrivals_tick, 60)):
        threading.Thread(target=loop, args=(fn, every), daemon=True).start()
    log("home on port", PORT)
    make_server(PORT).serve_forever()
