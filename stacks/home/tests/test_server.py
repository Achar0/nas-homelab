import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["NTFY_URL"] = ""
import server  # noqa: E402


class Proxy(unittest.TestCase):
    def test_proxy_allowlist(self):
        self.assertEqual(server.prom_target("/api/prom/query", "query=up"), "http://127.0.0.1:9090/api/v1/query?query=up")
        self.assertIsNone(server.prom_target("/api/prom/query_range", "x"))   # Home only needs instant values
        self.assertIsNone(server.prom_target("/api/prom/admin/tsdb/delete_series", ""))


class Tick(unittest.TestCase):
    def test_save_failure_still_updates_and_pushes(self):
        sent = []
        bad = {"netwatch": None, "kuma": None, "restarts": None, "ab_missing": None,
               "prom": {"md_active": 1, "md_required": 2}}
        orig_save, orig_push = server.save_state, server.send_push
        server.save_state = lambda: (_ for _ in ()).throw(OSError("disk full"))
        server.send_push = lambda t, d: sent.append(t)
        server.STATE.clear()
        try:
            server.attention_tick(gather=lambda now: (bad, []))
        finally:
            server.save_state, server.send_push = orig_save, orig_push
        self.assertEqual(sent, ["RAID degraded"])
        self.assertEqual(server.LATEST["attention"]["urgent"]["id"], "raid")


class Limits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import http.server
        import time as _t

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                if self.path == "/big":
                    self.wfile.write(b"x" * 300_000)
                elif self.path == "/slow":
                    for _ in range(30):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        _t.sleep(0.1)
                else:
                    self.wfile.write(b"ok")

            def log_message(self, *a):
                pass
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_small_body_ok(self):
        self.assertEqual(server.get_limited(self.base + "/ok", limit=1000, deadline=2), b"ok")

    def test_too_big_rejected(self):
        with self.assertRaises(ValueError):
            server.get_limited(self.base + "/big", limit=100_000, deadline=5)

    def test_trickle_hits_deadline(self):
        with self.assertRaises(TimeoutError):
            server.get_limited(self.base + "/slow", limit=100_000, deadline=1)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, method="GET"):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None

    def setUp(self):
        server.STATE.clear()
        server.STATE.update({"incidents": {"space": {"started": 1, "pushed": False, "dismissed": False, "acked": False,
                                                     "resolved_at": None, "level": "normal", "title": "Free space low",
                                                     "detail": "10% free", "src": "prom", "app": "mission"}}})
        server.LATEST["attention"] = {"items": [], "urgent": None, "sources_down": []}

    def test_dismiss_persists(self):
        code, _ = self.req("/api/attention/space/dismiss", "POST")
        self.assertEqual(code, 200)
        with open(server.STATE_PATH) as f:
            self.assertTrue(json.load(f)["incidents"]["space"]["dismissed"])

    def test_post_only_known_ids(self):
        self.assertEqual(self.req("/api/attention/nope/dismiss", "POST")[0], 404)
        self.assertEqual(self.req("/api/attention/space/delete", "POST")[0], 404)
        self.assertEqual(self.req("/api/news", "POST")[0], 404)

    def test_demo_never_pushed(self):
        sent = []
        orig, server.send_push = server.send_push, lambda *a: sent.append(a)
        try:
            code, body = self.req("/api/attention?demo=urgent")
        finally:
            server.send_push = orig
        self.assertEqual(code, 200)
        self.assertEqual(body["urgent"]["id"], "demo")
        self.assertEqual(sent, [])
        self.assertNotIn("demo", server.STATE["incidents"])

    def test_demo_many_shows_priorities(self):
        code, body = self.req("/api/attention?demo=many")
        self.assertEqual(code, 200)
        self.assertEqual([i["level"] for i in body["items"]][:3], ["urgent", "urgent", "normal"])
        self.assertTrue(body["items"][1]["acked"])
        self.assertFalse(any(k.startswith("demo") for k in server.STATE["incidents"]))

    def test_open_is_recorded_and_listed(self):
        import news_db
        news_db.store(server.NEWS_DB, [{"id": "abc", "title": "T", "summary": "S", "link": "https://x", "source": "Src",
                                        "topic": "tech", "lang": "en", "published": 1}], 1000)
        self.assertEqual(self.req("/api/news/abc/open", "POST")[0], 200)
        self.assertEqual(self.req("/api/news/zzz/open", "POST")[0], 404)
        code, body = self.req("/api/news?topic=opened")
        self.assertEqual(code, 200)
        self.assertEqual([i["id"] for i in body["items"]], ["abc"])

    def test_no_traversal(self):
        self.assertEqual(self.req("/../server.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
