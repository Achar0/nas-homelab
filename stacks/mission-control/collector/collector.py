"""Mission Control collector: container + service metrics for Prometheus.

Every 15 s it asks Docker (read-only proxy), qBittorrent, AdGuard, Speedtest
Tracker and Tailscale for their numbers and serves them on 127.0.0.1:9101/metrics.
One broken source never hides the others: it just reports mc_up{source=...} 0.
"""
import base64
import http.client
import http.cookiejar
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sources

E = os.environ.get
PORT = int(E("PORT", "9101"))
POLL_S = 15
DOCKER = E("DOCKER_URL", "http://127.0.0.1:2375")
QBT = E("QBT_URL", "http://127.0.0.1:8888")
ADGUARD = E("ADGUARD_URL", "http://127.0.0.1:8080")
SPEEDTEST = E("SPEEDTEST_URL", "http://127.0.0.1:8765")
TS_SOCKET = E("TAILSCALE_SOCKET", "/ts/tailscaled.sock")


def get_json(url, headers=None, opener=None):
    req = urllib.request.Request(url, headers=headers or {})
    with (opener.open(req, timeout=10) if opener else urllib.request.urlopen(req, timeout=10)) as r:
        return json.loads(r.read())


def fetch_docker():
    containers = [c for c in get_json(DOCKER + "/containers/json") if c["State"] == "running"]

    def one(c):  # stream=false waits ~1 s so precpu_stats is filled
        try:
            return c["Id"], get_json(f"{DOCKER}/containers/{c['Id']}/stats?stream=false")
        except OSError:  # removed/recreated between the list and this call: skip just this one
            return c["Id"], None

    with ThreadPoolExecutor(8) as pool:
        stats = dict(pool.map(one, containers))
    return sources.parse_docker(containers, stats)


class Qbt:
    """qBittorrent Web API session: keeps the login cookie, logs in again when it expires."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("Referer", QBT)]

    def login(self):
        body = urllib.parse.urlencode({"username": E("QBT_USER", ""), "password": E("QBT_PASS", "")}).encode()
        if self.op.open(QBT + "/api/v2/auth/login", body, timeout=10).read() != b"Ok.":
            raise RuntimeError("qBittorrent login refused")

    def get(self, path):
        try:
            return get_json(QBT + path, opener=self.op)
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            self.login()
            return get_json(QBT + path, opener=self.op)

    def __call__(self):
        return sources.parse_qbt(self.get("/api/v2/transfer/info"), self.get("/api/v2/torrents/info"),
                                 self.get("/api/v2/sync/maindata"))


def fetch_adguard():
    auth = base64.b64encode(f"{E('ADGUARD_USER', '')}:{E('ADGUARD_PASS', '')}".encode()).decode()
    return sources.parse_adguard(get_json(ADGUARD + "/control/stats", {"Authorization": "Basic " + auth}))


def fetch_speedtest():
    headers = {"Authorization": "Bearer " + E("SPEEDTEST_KEY", ""), "Accept": "application/json"}
    return sources.parse_speedtest(get_json(SPEEDTEST + "/api/v1/results/latest", headers))


class _UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(10)
        self.sock.connect(TS_SOCKET)


def fetch_tailscale():
    c = _UnixHTTP("local-tailscaled.sock")
    c.request("GET", "/localapi/v0/status", headers={"Host": "local-tailscaled.sock"})
    r = c.getresponse()
    if r.status != 200:
        raise RuntimeError(f"tailscale status {r.status}")
    return sources.parse_tailscale(json.loads(r.read()), now=int(time.time()))


def collect_all(fetchers):
    """Run every fetcher; a failing one only flips its mc_up to 0."""
    out = []
    for name, fetch in fetchers.items():
        try:
            out += fetch()
            ok = 1
        except Exception as e:  # noqa: BLE001 - any failure of one source must not stop the rest
            print(time.strftime("%H:%M:%S"), name, "failed:", e, flush=True)
            ok = 0
        out.append(("mc_up", {"source": name}, ok))
    return out


FETCHERS = {"docker": fetch_docker, "qbittorrent": Qbt(), "adguard": fetch_adguard,
            "speedtest": fetch_speedtest, "tailscale": fetch_tailscale}
latest = {"text": ""}


def worker():
    while True:
        latest["text"] = sources.render(collect_all(FETCHERS))
        time.sleep(POLL_S)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = latest["text"].encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
