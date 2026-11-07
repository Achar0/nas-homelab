"""Mission Control web server (:8800).

Serves the page, the vendored JS libraries, and these read-only proxies:
  /api/prom/query, /api/prom/query_range -> Prometheus (127.0.0.1:9090)
  /api/netwatch                          -> Netwatch /api/state
  /api/layout                            -> Home /api/internal/layout (dock and card order from Settings)
Nothing else of Prometheus (e.g. its admin API) is reachable through here.
"""
import os
import shutil
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import auth

PORT = int(os.environ.get("PORT", "8800"))
PROM = os.environ.get("PROM_URL", "http://127.0.0.1:9090")
NETWATCH = os.environ.get("NETWATCH_URL", "http://127.0.0.1:8790")
HOME = os.environ.get("HOME_URL", "http://127.0.0.1:3001")
DATA = os.environ.get("DATA_DIR", "/data")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PROM_ALLOWED = {"/api/prom/query": "/api/v1/query", "/api/prom/query_range": "/api/v1/query_range"}
VENDOR = {  # pinned versions, downloaded once into DATA/vendor (the page never loads a CDN)
    "uPlot.iife.min.js": "https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.iife.min.js",
    "uPlot.min.css": "https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.min.css",
    "globe.gl.min.js": "https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js",
    "countries-110m.json": "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json",
    "topojson-client.min.js": "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js",
}
TYPES = {".js": "text/javascript", ".css": "text/css", ".json": "application/json"}


def prom_target(path, qs):
    """Upstream Prometheus URL for an allowed proxy path, else None."""
    api = PROM_ALLOWED.get(path)
    return f"{PROM}{api}?{qs}" if api else None


def ensure_vendor():
    os.makedirs(os.path.join(DATA, "vendor"), exist_ok=True)
    for name, url in VENDOR.items():
        p = os.path.join(DATA, "vendor", name)
        if os.path.exists(p):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mission-control-nas/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(p + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(p + ".part", p)
            print("vendor", name, "ok", flush=True)
        except OSError as e:
            print("vendor", name, "failed:", e, flush=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def send_bytes(self, code, body, ctype, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def proxy(self, url):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                self.send_bytes(200, r.read(), "application/json")
        except urllib.error.HTTPError as e:  # Prometheus explains bad queries in its body
            self.send_bytes(e.code, e.read(), "application/json")
        except OSError as e:
            self.send_bytes(502, ('{"error": "%s"}' % type(e).__name__).encode(), "application/json")

    def do_HEAD(self):
        if auth.require_login(self):
            super().do_HEAD()

    def do_GET(self):
        if not auth.require_login(self):   # every path: page, vendor files and data
            return None
        path, _, qs = self.path.partition("?")
        if path.startswith("/api/prom/"):
            url = prom_target(path, qs)
            return self.proxy(url) if url else self.send_error(404)
        if path == "/api/netwatch":
            return self.proxy(NETWATCH + "/api/state")
        if path == "/api/layout":
            return self.proxy(HOME + "/api/internal/layout")
        if path.startswith("/vendor/"):
            name = path[len("/vendor/"):]
            p = os.path.join(DATA, "vendor", name)
            if name not in VENDOR or not os.path.exists(p):
                return self.send_error(404)
            with open(p, "rb") as f:
                body = f.read()
            return self.send_bytes(200, body, TYPES.get(os.path.splitext(name)[1], "application/octet-stream"),
                                   "public, max-age=604800")
        return super().do_GET()  # static files; translate_path() keeps them inside STATIC

    def end_headers(self):
        if not any(h.startswith(b"Cache-Control") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *a):
        pass


def make_server(port):
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    auth.startup_check(lambda msg: print(msg, flush=True))
    ensure_vendor()
    print("mission control on port", PORT, flush=True)
    make_server(PORT).serve_forever()
