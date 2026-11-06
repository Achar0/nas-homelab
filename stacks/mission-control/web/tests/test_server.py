import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
import server  # noqa: E402


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
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
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


if __name__ == "__main__":
    unittest.main()
