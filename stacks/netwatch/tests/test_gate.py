"""Netwatch needs the admin login, except for Home and Mission Control on the same machine."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.modules.setdefault("maxminddb", types.ModuleType("maxminddb"))   # only used by the worker
import app  # noqa: E402
import auth  # noqa: E402

KEY = "k" * 64


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ADMIN_AUTH_FILE"] = os.path.join(tempfile.mkdtemp(), "auth.json")
        with open(os.environ["ADMIN_AUTH_FILE"], "w") as f:
            json.dump({"hash": "scrypt:2:1:1:00:00", "key": KEY}, f)
        cls.httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.real = app.LOOPBACK
        app.LOOPBACK = set()   # the test client is on loopback: pretend it comes from the network

    def tearDown(self):
        app.LOOPBACK = self.real

    def call(self, path, method="GET", cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, headers={"Cookie": cookie} if cookie else {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def cookie(self):
        return f"nas_admin={auth.make_token(KEY, time.time() + 60)}"

    def test_pages_redirect_to_login(self):
        for path in ("/", "/index.html", "/vendor/countries-110m.json"):
            status, headers, _ = self.call(path)
            self.assertEqual(status, 302, path)
            self.assertIn(":3001/?login=1&next=", headers["Location"])

    def test_head_redirects_too(self):
        self.assertEqual(self.call("/", "HEAD")[0], 302)

    def test_data_refuses(self):
        for path in ("/api/state", "/api/state?x=1"):
            status, _, body = self.call(path)
            self.assertEqual(status, 401, path)
            self.assertNotIn(b"items", body)

    def test_with_a_session_the_page_opens(self):
        self.assertEqual(self.call("/", cookie=self.cookie())[0], 200)

    def test_the_machine_itself_skips_the_login(self):
        app.LOOPBACK = self.real
        self.assertEqual(self.call("/api/state")[0], 200)

    def test_expired_session_refuses(self):
        old = f"nas_admin={auth.make_token(KEY, time.time() - 1)}"
        self.assertEqual(self.call("/api/state", cookie=old)[0], 401)


if __name__ == "__main__":
    unittest.main()
