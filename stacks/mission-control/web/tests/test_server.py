import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
import auth  # noqa: E402
import server  # noqa: E402

KEY = "k" * 64
os.environ["ADMIN_AUTH_FILE"] = os.path.join(tempfile.mkdtemp(), "auth.json")
with open(os.environ["ADMIN_AUTH_FILE"], "w") as f:
    json.dump({"hash": "scrypt:2:1:1:00:00", "key": KEY}, f)


def cookie():
    return {"Cookie": f"nas_admin={auth.make_token(KEY, time.time() + 60)}"}


class Proxy(unittest.TestCase):
    def test_proxy_allowlist(self):
        self.assertEqual(server.prom_target("/api/prom/query_range", "query=up&start=1&end=2&step=15"),
                         "http://127.0.0.1:9090/api/v1/query_range?query=up&start=1&end=2&step=15")
        self.assertEqual(server.prom_target("/api/prom/query", "query=up"),
                         "http://127.0.0.1:9090/api/v1/query?query=up")
        self.assertIsNone(server.prom_target("/api/prom/admin/tsdb/delete_series", ""))
        self.assertIsNone(server.prom_target("/api/prom/../admin", ""))
        self.assertIsNone(server.prom_target("/api/prom/query/../../admin", ""))


class Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def code(self, path, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=cookie())
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_static_no_traversal(self):
        self.assertEqual(self.code("/../server.py"), 404)
        self.assertEqual(self.code("/%2e%2e/server.py"), 404)
        self.assertEqual(self.code("/vendor/../../server.py"), 404)

    def test_only_get(self):
        self.assertIn(self.code("/api/prom/query?query=up", "POST"), (405, 501))


class Gate(unittest.TestCase):
    """Nothing on Mission Control answers without the admin login."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, method="GET", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def test_pages_redirect_to_login(self):
        for path in ("/", "/app.js", "/index.html", "/vendor/uplot.js", "/nope"):
            status, headers, body = self.call(path)
            self.assertEqual(status, 302, path)
            self.assertIn(":3001/?login=1&next=", headers["Location"])
            self.assertEqual(body, b"")

    def test_head_redirects_too(self):
        self.assertEqual(self.call("/", "HEAD")[0], 302)

    def test_data_refuses(self):
        for path in ("/api/prom/query?query=up", "/api/prom/query_range?query=up", "/api/netwatch"):
            self.assertEqual(self.call(path)[0], 401, path)

    def test_with_a_session_the_page_opens(self):
        self.assertEqual(self.call("/", headers=cookie())[0], 200)

    def test_plain_http_from_the_network_is_redirected_in_https_mode(self):
        os.environ["NAS_TS_NAME"] = "nas.example.ts.net"
        self.addCleanup(os.environ.pop, "NAS_TS_NAME", None)
        real = auth.LOOPBACK
        auth.LOOPBACK = set()   # the test client is on loopback: pretend it comes from the network
        self.addCleanup(setattr, auth, "LOOPBACK", real)
        status, headers, _ = self.call("/")
        self.assertEqual((status, headers["Location"]), (301, "https://nas.example.ts.net:8843/"))
        self.assertEqual(self.call("/api/netwatch")[0], 403)

    def test_expired_session_refuses(self):
        old = {"Cookie": f"nas_admin={auth.make_token(KEY, time.time() - 1)}"}
        self.assertEqual(self.call("/api/netwatch", headers=old)[0], 401)


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = server.make_server(0)
        cls.port = cls.web.server_address[1]
        threading.Thread(target=cls.web.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()

    def setUp(self):
        self.addCleanup(setattr, server, "HOME", server.HOME)

    def call(self, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/layout", headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def test_layout_needs_login(self):
        self.assertEqual(self.call()[0], 401)

    def test_layout_proxies_home(self):
        class Home(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        home = ThreadingHTTPServer(("127.0.0.1", 0), Home)
        self.addCleanup(home.server_close)
        self.addCleanup(home.shutdown)
        threading.Thread(target=home.serve_forever, daemon=True).start()
        server.HOME = f"http://127.0.0.1:{home.server_address[1]}"
        status, body = self.call(cookie())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"path": "/api/internal/layout"})

    def test_layout_502_when_home_is_down(self):
        server.HOME = "http://127.0.0.1:1"
        self.assertEqual(self.call(cookie())[0], 502)



if __name__ == "__main__":
    unittest.main()
