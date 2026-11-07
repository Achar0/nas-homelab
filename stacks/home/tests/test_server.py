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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["NTFY_URL"] = ""
AUTH_FILE = os.path.join(tempfile.mkdtemp(), "auth.json")
import auth  # noqa: E402
import server  # noqa: E402

KEY = "k" * 64


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


class PhoneSwitch(unittest.TestCase):
    def setUp(self):
        self.sent = []
        real, reset = server.send_push, dict(server.STATE)
        server.send_push = lambda title, detail: self.sent.append(title)
        self.addCleanup(setattr, server, "send_push", real)
        server.STATE.clear()
        self.addCleanup(lambda: (server.STATE.clear(), server.STATE.update(reset)))
        self.addCleanup(lambda: server.STORE.update(lambda s: s["alerts"].update(push=True)))

    def gather(self, now):
        return {"prom": {"md_active": 1, "md_required": 2}}, []

    def test_push_on_sends(self):
        server.attention_tick(self.gather)
        self.assertEqual(self.sent, ["RAID degraded"])

    def test_push_off_sends_nothing_and_never_sends_later(self):
        server.STORE.update(lambda s: s["alerts"].update(push=False))
        server.attention_tick(self.gather)
        self.assertEqual(self.sent, [])
        server.STORE.update(lambda s: s["alerts"].update(push=True))
        server.attention_tick(self.gather)
        self.assertEqual(self.sent, [])

    def test_ticks_use_the_stored_numbers(self):
        server.STORE.update(lambda s: s["alerts"].update(hot_c=40))
        self.addCleanup(lambda: server.STORE.update(lambda s: s["alerts"].update(hot_c=50)))
        server.attention_tick(lambda now: ({"prom": {"drive_temp": {"sda": 45}}}, []))
        self.assertEqual([i["id"] for i in server.LATEST["attention"]["items"]], ["hot:sda"])


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


class WholeFetchDeadline(unittest.TestCase):
    def serve(self, handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{srv.server_address[1]}/"

    def test_redirect_chain_can_not_outlast_the_deadline(self):
        class Slow(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(0.4)
                self.send_response(302)
                self.send_header("Location", f"/{time.time()}")
                self.end_headers()

            def log_message(self, *a):
                pass
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            server.get_limited(self.serve(Slow), deadline=1)
        self.assertLess(time.monotonic() - start, 1.5)

    def test_slow_headers_then_gap_can_not_outlast_the_deadline(self):
        class Slow(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(0.7)
                self.send_response(200)
                self.send_header("Content-Length", "10")
                self.end_headers()
                self.wfile.flush()
                time.sleep(0.8)
                self.wfile.write(b"0123456789")

            def log_message(self, *a):
                pass
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            server.get_limited(self.serve(Slow), deadline=1)
        self.assertLess(time.monotonic() - start, 1.3)

    def test_normal_fetch_still_returns_the_data(self):
        class Fine(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass
        self.assertEqual(server.get_limited(self.serve(Fine)), b"ok")


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
        os.environ["ADMIN_AUTH_FILE"] = AUTH_FILE
        with open(AUTH_FILE, "w") as f:
            json.dump({"hash": "scrypt:2:1:1:00:00", "key": KEY}, f)
        cookie = f"nas_admin={auth.make_token(KEY, time.time() + 60)}"
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=b"" if method == "POST" else None,
                                   headers={"Cookie": cookie})
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

    def test_attention_api_reports_push_state(self):
        self.assertIs(self.req("/api/attention")[1]["push"], True)
        server.STORE.update(lambda s: s["alerts"].update(push=False))
        self.addCleanup(lambda: server.STORE.update(lambda s: s["alerts"].update(push=True)))
        self.assertIs(self.req("/api/attention")[1]["push"], False)

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
