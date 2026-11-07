"""The owner's preferences: one JSON file in Home's data folder.

Built-in defaults equal how things worked before Settings existed, so nothing changes until the
owner changes it. A file that can't be trusted is kept aside, never overwritten, and Home runs on the
defaults: broken settings must not silence alerts.
"""
import copy
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.parse

ALERT_LIMITS = {"free_pct": (5, 50), "service_down_min": (1, 60), "intrusion_min": (1, 60), "hot_c": (40, 70), "slow_pct": (10, 90)}
TOPICS = ("tech", "markets", "discoveries")
LANGS = ("en", "it")
STATES = ("known", "new", "ignored")
PLAIN_ICON = "mdi-view-dashboard.svg"
NAME_LIMIT = 40


def service(sid, name, icon, mono, port, container=None, scheme="http", settings_path="", on_dock=True):
    return {"id": sid, "name": name, "icon": icon, "mono": mono, "port": port, "scheme": scheme,
            "settings_path": settings_path, "container": container, "on_dock": on_dock, "state": "known",
            "running": True, "port_options": []}


SEED_SERVICES = (
    service("home", "Home", "mdi-home.svg", True, 3001, "home-3001"),
    service("mission", "Mission Control", "mdi-monitor-dashboard.svg", True, 8800, "mc-web-8800"),
    service("adguard", "AdGuard", "adguard-home.svg", False, 8080, "adguardhome-8080", settings_path="/#settings"),
    service("qbittorrent", "qBittorrent", "qbittorrent.svg", False, 8888, "qbittorrent-app-1"),
    service("autobangumi", "AutoBangumi", "mdi-television-classic.svg", True, 7892, "autobangumi-7892"),
    service("speedtest", "Speedtest", "speedtest-tracker.svg", False, 8765, "speedtest-tracker-8765", settings_path="/admin"),
    service("kuma", "Uptime Kuma", "uptime-kuma.svg", False, 3002, "uptime-kuma-3002", settings_path="/settings/general"),
    service("dockge", "Dockge", "dockge.svg", False, 5001, "dockge-5001", settings_path="/settings/general"),
    service("netwatch", "Netwatch", "mdi-earth.svg", True, 8790, "netwatch-8790"),
    service("glances", "Glances", "glances.svg", False, 61208, "glances-61208"),
    service("ugos", "UGOS", "mdi-nas.svg", True, 9443, scheme="https"),
    service("firefox", "Firefox", PLAIN_ICON, True, 5888, "firefox-app-1", on_dock=False),
)


def feed_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _shown(*ids):
    return [{"id": i, "show": True} for i in ids]


def default_settings(feeds):
    return {
        "version": 1,
        "feeds": [{"id": feed_id(f["url"]), "name": f["name"], "url": f["url"], "topic": f["topic"], "lang": f["lang"],
                   "enabled": True} for f in feeds],
        "alerts": {"free_pct": 15, "service_down_min": 2, "intrusion_min": 3, "hot_c": 50, "slow_pct": 50, "push": True},
        "services": copy.deepcopy(list(SEED_SERVICES)),
        "rail": {"nas": _shown("cpu", "memory", "temperature", "free"), "services": _shown("qbittorrent", "adguard", "speedtest")},
        "cards": _shown("qbittorrent", "adguard", "speedtest", "tailscale", "connections"),
        "known_containers": None,
    }


def _need(ok, what):
    if not ok:
        raise ValueError(what)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _text(v, what):
    _need(isinstance(v, str) and v.strip(), what)


def _check_feed(f):
    _need(isinstance(f, dict), "feed")
    _text(f.get("id"), "feed id")
    _text(f.get("name"), "feed name")
    _text(f.get("url"), "feed url")
    _need(urllib.parse.urlsplit(f["url"]).scheme in ("http", "https"), "feed url")
    _need(f.get("topic") in TOPICS, "feed topic")
    _need(f.get("lang") in LANGS, "feed language")
    _need(isinstance(f.get("enabled"), bool), "feed enabled")


def _check_alerts(a):
    for key, (low, high) in ALERT_LIMITS.items():
        _need(_is_int(a.get(key)) and low <= a[key] <= high, key)
    _need(isinstance(a.get("push"), bool), "push")


def _check_service(s):
    _need(isinstance(s, dict), "service")
    _text(s.get("id"), "service id")
    _text(s.get("name"), "service name")
    _need(len(s["name"]) <= NAME_LIMIT, "service name")
    _text(s.get("icon"), "service icon")
    port = s.get("port")
    _need(port is None or (_is_int(port) and 1 <= port <= 65535), "port")
    _need(s.get("scheme") in ("http", "https"), "scheme")
    _need(isinstance(s.get("settings_path"), str) and (not s["settings_path"] or s["settings_path"].startswith("/")), "settings path")
    _need(s.get("container") is None or isinstance(s["container"], str), "container")
    _need(isinstance(s.get("on_dock"), bool) and isinstance(s.get("mono"), bool) and isinstance(s.get("running"), bool), "service flags")
    _need(not s["on_dock"] or port is not None, "a service on the dock needs a port")
    _need(s.get("state") in STATES, "state")
    options = s.get("port_options")
    _need(isinstance(options, list) and all(_is_int(p) and 1 <= p <= 65535 for p in options), "port options")


def _check_shown(items):
    _need(isinstance(items, list), "list")
    for x in items:
        _need(isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("show"), bool), "list item")


def normalize(raw, defaults):
    """A complete, checked copy: missing sections come from defaults, wrong values raise ValueError."""
    _need(isinstance(raw, dict), "settings")
    out = copy.deepcopy(defaults)
    for key in ("feeds", "services", "cards", "known_containers"):
        if key in raw:
            out[key] = copy.deepcopy(raw[key])
    for key in ("alerts", "rail"):
        if key in raw:
            _need(isinstance(raw[key], dict), key)
            out[key].update(copy.deepcopy(raw[key]))
    _need(isinstance(out["feeds"], list) and isinstance(out["services"], list), "lists")
    for f in out["feeds"]:
        _check_feed(f)
    _check_alerts(out["alerts"])
    for s in out["services"]:
        _check_service(s)
    _need(len({s["id"] for s in out["services"]}) == len(out["services"]), "service ids")
    _check_shown(out["rail"]["nas"])
    _check_shown(out["rail"]["services"])
    _check_shown(out["cards"])
    known = out["known_containers"]
    _need(known is None or (isinstance(known, list) and all(isinstance(k, str) for k in known)), "known containers")
    return out


class Store:
    def __init__(self, path, feeds_path):
        self.path = path
        self.problem = None
        self._lock = threading.Lock()
        self._defaults = default_settings(self._read_feeds(feeds_path))
        self._value = self._load()

    @staticmethod
    def _read_feeds(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _load(self):
        try:
            with open(self.path) as f:
                return normalize(json.load(f), self._defaults)
        except FileNotFoundError:
            return copy.deepcopy(self._defaults)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            aside = f"{self.path}.bad-{int(time.time())}"
            try:
                os.replace(self.path, aside)
                self.problem = f"Your settings file couldn't be read, so defaults are in use. It was saved as {os.path.basename(aside)}."
            except OSError:
                self.problem = "Your settings file couldn't be read, so defaults are in use."
            print(time.strftime("%H:%M:%S"), "settings file unusable:", type(e).__name__, flush=True)
            return copy.deepcopy(self._defaults)

    def get(self):
        with self._lock:
            return copy.deepcopy(self._value)

    def _write(self, value):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(value, f)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def update(self, fn):
        """Change the settings under the lock. fn edits a copy; returning False means nothing changed."""
        with self._lock:
            draft = copy.deepcopy(self._value)
            if fn(draft) is False:
                return copy.deepcopy(self._value)
            new = normalize(draft, self._defaults)
            self._write(new)
            self._value = new
            return copy.deepcopy(new)
