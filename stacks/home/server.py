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
import http.client
import http.cookiejar
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import arrivals
import attention
import auth
import discovery
import feeds
import guest
import news_db
import settings
import weather

E = os.environ.get
PORT = int(E("PORT", "3001"))
DATA = E("DATA_DIR", "/data")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
STATE_PATH = os.path.join(DATA, "state.json")
SETTINGS_PATH = os.path.join(DATA, "settings.json")
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
SETTINGS_BODY_LIMIT = 65536
FEED_NAME_LIMIT = 80
LOOPBACK = {"127.0.0.1", "::1"}   # Mission Control and Netwatch on this machine; no reverse proxy runs in front
SHOW_LISTS = {"rail_nas": lambda s: s["rail"]["nas"], "rail_services": lambda s: s["rail"]["services"], "cards": lambda s: s["cards"]}
FEEDS_WAKE = threading.Event()   # set to refresh the news now instead of at the next 15-minute cycle
THROTTLE = auth.Throttle()
login_lock = threading.Lock()   # one password check at a time: scrypt is deliberately expensive
lock = threading.Lock()
os.makedirs(DATA, exist_ok=True)
STORE = settings.Store(SETTINGS_PATH, os.path.join(HERE, "feeds.json"))
STATE = {}
LATEST = {"attention": {"items": [], "urgent": None, "sources_down": []}, "news": [], "news_errors": [],
          "news_updated": 0, "arrivals": {"arrived": [], "downloading": []}, "inputs": None, "inputs_at": 0, "weather": None}


def alert_rules():
    """The stored alert numbers and phone switch."""
    return STORE.get()["alerts"]


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


def _download(url, limit, deadline):
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


def get_limited(url, limit=FEED_LIMIT, deadline=FEED_DEADLINE):
    """The whole fetch within the deadline. In a thread because redirects, slow headers and DNS happen
    inside urlopen, out of reach of any check between reads. A late thread ends with its socket timeout."""
    box = {}

    def work():
        try:
            box["data"] = _download(url, limit, deadline)
        except Exception as e:  # noqa: BLE001 - handed to the caller below
            box["error"] = e
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        raise TimeoutError(f"{url}: slower than {deadline} s")
    if "error" in box:
        raise box["error"]
    return box["data"]


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


def read_containers():
    return json.loads(get(DOCKER + "/containers/json?all=1"))


def read_restarts(now, containers):
    if containers is None:
        raise OSError("docker proxy unavailable")
    out = {}
    for c in containers:
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
    inputs, down = {"ab_missing": None, "containers": None}, []
    try:
        inputs["containers"] = read_containers()
    except Exception as e:  # noqa: BLE001 - same as the sources below
        log("containers unavailable:", e)
    for key, read in (("netwatch", lambda: json.loads(get(NETWATCH + "/api/state"))), ("kuma", read_kuma),
                      ("prom", read_prom), ("restarts", lambda: read_restarts(now, inputs["containers"]))):
        try:
            inputs[key] = read()
        except Exception as e:  # noqa: BLE001 - a source being down must not stop the others
            inputs[key] = None
            log(key, "unavailable:", e)
        if inputs[key] is None:
            down.append(key)
    return inputs, down


def scan_containers(containers):
    try:
        STORE.update(lambda s: discovery.apply(s, containers))
    except Exception as e:  # noqa: BLE001 - disk full, nonsense from Docker: alerts matter more, just log it
        log("container scan failed:", e)


def attention_tick(gather=gather_inputs):
    now = time.time()
    inputs, down = gather(now)
    scan_containers(inputs.get("containers"))
    rules = alert_rules()
    with lock:
        items, urgent, pushes = attention.evaluate(inputs, STATE, now, rules)
        LATEST["attention"] = {"items": items, "urgent": urgent, "sources_down": down}
        LATEST["inputs"], LATEST["inputs_at"] = inputs, now   # raw readings for the guest status line
        try:
            save_state()
        except OSError as e:   # e.g. disk full: keep showing and pushing, just log it
            log("state not saved:", e)
    if rules["push"]:   # while off, a problem counts as already pushed: nothing is sent later
        for p in pushes:
            send_push(p["title"], p["detail"])


def feeds_tick():
    cfg = [f for f in STORE.get()["feeds"] if f["enabled"]]
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


def weather_tick():
    # A failed fetch raises here, so the previous weather stays until weather.fresh() retires it
    LATEST["weather"] = weather.build(json.loads(get_limited(weather.URL)), datetime.now(), time.time())


def feeds_loop():
    while True:
        FEEDS_WAKE.clear()   # before fetching: a change made during the fetch runs it again
        try:
            feeds_tick()
        except Exception as e:  # noqa: BLE001 - keep the worker alive
            log("feeds_tick failed:", e)
        FEEDS_WAKE.wait(900)


def loop(fn, every):
    while True:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - keep the worker alive
            log(fn.__name__, "failed:", e)
        time.sleep(every)


# ---------- HTTP ----------
def layout_view():
    """What the pages need to draw docks, rails and cards. Mission Control gets this without a login: keep it minimal."""
    s = STORE.get()
    fields = ("id", "name", "icon", "mono", "port", "scheme")
    return {"dock": [{k: x[k] for k in fields} for x in s["services"] if x["on_dock"]],
            "rail": s["rail"], "cards": s["cards"], "push": s["alerts"]["push"]}


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


def _edit_service(s, sid, **changes):
    next(x for x in s["services"] if x["id"] == sid).update(changes)


def _in_order(rows, ids):
    """rows rearranged to follow ids, which must name each row exactly once."""
    by_id = {x["id"]: x for x in rows}
    if sorted(ids) != sorted(by_id):
        raise ValueError("the list changed, reload the page")
    return [by_id[i] for i in ids]


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
            data = guest.summary(LATEST["inputs"], LATEST["arrivals"], time.time(), LATEST["inputs_at"], alert_rules())
            demo = guest.DEMO.get((q.get("demo") or [""])[0])
            return self.json({**data, "status": demo} if demo else data)
        if path == "/tv":   # the TV's WebView gets the page directly, without a redirect to /tv/
            self.path = "/tv/index.html"
            return super().do_GET()
        if path == "/api/public/tv":
            data = guest.tv(LATEST["inputs"], LATEST["arrivals"], LATEST["weather"], time.time(), LATEST["inputs_at"], alert_rules())
            demo = guest.DEMO.get((q.get("demo") or [""])[0])
            return self.json({**data, "status": guest.tv_status(demo)} if demo else data)
        if path == "/api/news" and "opened" not in q.get("topic", []):
            topic = (q.get("topic") or ["all"])[0]
            items = [i for i in LATEST["news"] if topic == "all" or i["topic"] == topic]
            data = {"items": items, "updated": LATEST["news_updated"]}
            return self.json({**data, "errors": LATEST["news_errors"]} if self.logged_in() else data)
        if path == "/api/internal/layout":
            if self.client_address[0] in LOOPBACK:
                return self.json(layout_view())
            return self.json({"error": "login required"}, 401)
        if path.startswith("/api/"):
            if not auth.require_login(self):
                return None
        elif self.is_admin_file():
            if not auth.require_login(self):
                return None
            if self.translate_path(self.path) == ADMIN_STATIC and not path.endswith("/"):
                return self.redirect("/admin/")
        if path == "/api/layout":
            return self.json(layout_view())
        if path == "/api/settings":
            view = STORE.get()
            del view["known_containers"]
            return self.json({**view, "problem": STORE.problem})
        if path == "/api/attention":
            data = {**LATEST["attention"], "push": alert_rules()["push"]}
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
        if path in ("/admin/settings", "/admin/settings/"):
            self.path = "/admin/settings.html"
        return super().do_GET()

    def from_another_site(self):
        """SameSite doesn't separate ports, so a page in another app on this NAS would still send our cookie.
        Browsers always send Origin on a cross-origin POST; no Origin means it isn't a page."""
        origin = self.headers.get("Origin")
        if origin is None:
            return False
        try:
            return urllib.parse.urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower()
        except ValueError:
            return True

    def refuse_form(self):
        """Changes that matter take JSON only, which a plain HTML form can't send. True if answered."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype == "application/json":
            return False
        self.close_connection = True   # the body stays unread
        self.json({"error": "JSON only"}, 415)
        return True

    def read_json(self, limit):
        """The request's JSON object, or None after answering 413 or 400."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length > limit:
            self.close_connection = True   # the body stays unread
            self.json({"error": "too big"}, 413)
            return None
        try:
            body = json.loads(self.rfile.read(length)) if length > 0 else None
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self.json({"error": "bad request"}, 400)
            return None
        return body

    def login(self):
        body = self.read_json(LOGIN_BODY_LIMIT)
        if body is None:
            return None
        if not isinstance(body.get("pw"), str):
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

    def change_password(self):
        if self.refuse_form():
            return None
        body = self.read_json(LOGIN_BODY_LIMIT)
        if body is None:
            return None
        current, new = body.get("current"), body.get("new")
        if not isinstance(current, str) or not isinstance(new, str):
            return self.json({"error": "bad request"}, 400)
        if len(new) < auth.MIN_PASSWORD_LEN:
            return self.json({"error": f"Use at least {auth.MIN_PASSWORD_LEN} characters."}, 400)
        addr, now = self.client_address[0], time.time()
        remembered = auth.was_remembered(self.headers.get("Cookie"), now)
        with login_lock:
            wait = THROTTLE.wait(addr, now)
            if wait:
                return self.json({"error": "wait", "retry_after": wait}, 429)
            try:
                changed = auth.change_password(current, new)
            except OSError as e:
                log("password not saved:", e.__class__.__name__)
                return self.json({"error": "Couldn't save the password on the NAS."}, 503)
            if not changed:
                THROTTLE.fail(addr, now)
                return self.json({"error": "wrong"}, 403)   # not 401: this session is still fine
            THROTTLE.reset(addr)
        return self.json({"ok": True}, cookie=auth.login_cookie(remembered, now))

    def logout_everywhere(self):
        if self.refuse_form():
            return None
        try:
            auth.log_out_everywhere()
        except (OSError, ValueError) as e:
            log("log out everywhere failed:", e.__class__.__name__)
            return self.json({"error": "Couldn't save the change on the NAS."}, 503)
        return self.json({"ok": True}, cookie=auth.logout_cookie())

    def save(self, fn, wake=False):
        """Apply one settings change and answer: 200, 400 if refused, 503 if it couldn't be written."""
        try:
            STORE.update(fn)
        except ValueError as e:
            return self.json({"error": f"Can't save that: {e}."}, 400)
        except OSError as e:
            log("settings not saved:", e)
            return self.json({"error": "Couldn't save the settings on the NAS."}, 503)
        if wake:
            FEEDS_WAKE.set()
        return self.json({"ok": True})

    def settings_post(self, parts):
        if self.refuse_form():
            return None
        body = self.read_json(SETTINGS_BODY_LIMIT)
        if body is None:
            return None
        if parts == ["feeds"]:
            return self.add_feed(body)
        if parts[:1] == ["feeds"] and len(parts) in (2, 3):
            return self.change_feed(parts[1], parts[2:], body)
        if parts == ["alerts"]:
            return self.change_alerts(body)
        if parts[:1] == ["services"] and len(parts) in (2, 3):
            return self.change_service(parts[1], parts[2:], body)
        if parts == ["order"]:
            return self.change_order(body)
        if parts == ["show"]:
            return self.change_show(body)
        return self.send_error(404)

    def change_alerts(self, body):
        if not body or not set(body) <= {*settings.ALERT_LIMITS, "push"}:
            return self.json({"error": "bad request"}, 400)
        return self.save(lambda s: s["alerts"].update(body))

    def change_service(self, sid, action, body):
        row = next((x for x in STORE.get()["services"] if x["id"] == sid), None)
        if row is None:
            return self.send_error(404)
        if action == ["ignore"]:
            if row["state"] != "new":
                return self.json({"error": "Only a new service can be ignored."}, 400)
            return self.save(lambda s: _edit_service(s, sid, state="ignored", on_dock=False))
        if action == ["remove"]:
            if row["running"]:
                return self.json({"error": "Only a service that isn't running can be removed."}, 400)
            return self.save(lambda s: discovery.remove(s, sid))
        if action or not body or not set(body) <= {"name", "port", "on_dock", "scheme"}:
            return self.json({"error": "bad request"}, 400)
        changes = dict(body)
        if "name" in changes:
            if not isinstance(changes["name"], str):
                return self.json({"error": "Enter a name."}, 400)
            changes["name"] = changes["name"].strip()
        if changes.get("on_dock") is True:
            changes["state"] = "known"
        return self.save(lambda s: _edit_service(s, sid, **changes))

    def change_order(self, body):
        name, ids = body.get("list"), body.get("ids")
        if name != "dock" and name not in SHOW_LISTS or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return self.json({"error": "bad request"}, 400)

        def reorder(s):
            if name == "dock":   # only the settled rows have an order; new and ignored ones stay after them
                rows = [x for x in s["services"] if x["state"] == "known"]
                rest = [x for x in s["services"] if x["state"] != "known"]
                s["services"] = _in_order(rows, ids) + rest
            else:
                items = SHOW_LISTS[name](s)
                items[:] = _in_order(items, ids)
        return self.save(reorder)

    def change_show(self, body):
        name, iid, show = body.get("list"), body.get("id"), body.get("show")
        if name not in SHOW_LISTS or not isinstance(show, bool):
            return self.json({"error": "bad request"}, 400)

        def switch(s):
            row = next((x for x in SHOW_LISTS[name](s) if x["id"] == iid), None)
            if row is None:
                raise ValueError("unknown item")
            row["show"] = show
        return self.save(switch)

    def add_feed(self, body):
        url, topic, lang = body.get("url"), body.get("topic"), body.get("lang")
        try:
            scheme = urllib.parse.urlsplit(url.strip()).scheme if isinstance(url, str) else ""
        except ValueError:
            scheme = ""
        if scheme not in ("http", "https"):
            return self.json({"error": "Enter an address starting with http:// or https://."}, 400)
        url = url.strip()
        if topic not in settings.TOPICS or lang not in settings.LANGS:
            return self.json({"error": "Choose a topic and a language."}, 400)
        if any(f["url"] == url for f in STORE.get()["feeds"]):
            return self.json({"error": "That feed is already on the list."}, 400)
        try:
            data = get_limited(url)
        except (OSError, ValueError, http.client.HTTPException):
            return self.json({"error": "Couldn't read that address."}, 400)
        try:
            title = feeds.check(data)
        except ValueError:
            return self.json({"error": "That address isn't an RSS or Atom feed."}, 400)
        name = title or (urllib.parse.urlsplit(url).hostname or url).removeprefix("www.")
        new = {"id": settings.feed_id(url), "name": name[:FEED_NAME_LIMIT], "url": url, "topic": topic, "lang": lang, "enabled": True}

        def add(s):
            if any(f["url"] == url for f in s["feeds"]):   # checked again: the fetch ran outside the lock
                return False
            s["feeds"].append(new)
            return None
        return self.save(add, wake=True)

    def change_feed(self, fid, action, body):
        if not any(f["id"] == fid for f in STORE.get()["feeds"]):
            return self.send_error(404)
        if action == ["remove"]:
            return self.save(lambda s: s.update(feeds=[f for f in s["feeds"] if f["id"] != fid]), wake=True)
        if action or not isinstance(body.get("enabled"), bool):
            return self.json({"error": "bad request"}, 400)

        def switch(s):
            for f in s["feeds"]:
                if f["id"] == fid:
                    f["enabled"] = body["enabled"]
        return self.save(switch, wake=True)

    def do_POST(self):
        path = self.path.split("?")[0]
        if self.from_another_site():
            self.close_connection = True   # the body stays unread
            return self.json({"error": "wrong origin"}, 403)
        if path == "/api/login":
            return self.login()
        if path == "/api/logout":
            return self.json({"ok": True}, cookie=auth.logout_cookie())
        if not auth.require_login(self):
            return None
        parts = path.strip("/").split("/")
        if path == "/api/account/password":
            return self.change_password()
        if path == "/api/account/logout-everywhere":
            return self.logout_everywhere()
        if parts[:2] == ["api", "settings"]:
            return self.settings_post([urllib.parse.unquote(x) for x in parts[2:]])
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
                    items, urgent, _ = attention.evaluate({}, STATE, time.time(), alert_rules())   # no inputs: only re-render
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
    for fn, every in ((attention_tick, 30), (arrivals_tick, 60), (weather_tick, 1800)):
        threading.Thread(target=loop, args=(fn, every), daemon=True).start()
    threading.Thread(target=feeds_loop, daemon=True).start()
    log("home on port", PORT)
    make_server(PORT).serve_forever()
