"""Who can reach what on Home: the spec's route table, against a real server."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["NTFY_URL"] = ""
import auth  # noqa: E402
import server  # noqa: E402

KEY = "k" * 64
HOST = "127.0.0.1"
PW = "correct horse"
PW_HASH = auth.hash_password(PW)


AUTH_FILE = os.path.join(tempfile.mkdtemp(), "auth.json")


def write_auth(pw_hash, key):
    os.environ["ADMIN_AUTH_FILE"] = AUTH_FILE
    with open(AUTH_FILE, "w") as f:
        json.dump({"hash": pw_hash, "key": key}, f)


def remove_auth():
    os.environ["ADMIN_AUTH_FILE"] = AUTH_FILE
    if os.path.exists(AUTH_FILE):
        os.remove(AUTH_FILE)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_auth(PW_HASH, KEY)
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        remove_auth()

    def setUp(self):
        server.THROTTLE.reset(HOST)

    def call(self, path, method="GET", cookie=None, body=None):
        c = http.client.HTTPConnection(HOST, self.port, timeout=10)
        headers = {"Cookie": cookie} if cookie else {}
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def cookie(self, expires=None):
        return f"nas_admin={auth.make_token(KEY, expires or time.time() + 60)}"

    def login(self, pw=PW, remember=True, next_url=None):
        return self.call("/api/login", "POST", body=json.dumps({"pw": pw, "remember": remember, "next": next_url}))


class GuestRoutes(Base):
    def test_landing_page_has_no_dock(self):
        status, _, data = self.call("/")
        self.assertEqual(status, 200)
        self.assertNotIn(b"dock", data)
        self.assertNotIn(b"app.js", data)

    def test_owner_page_redirects_to_login_in_every_disguise(self):
        for path in ("/admin/", "/admin", "/admin/index.html", "/admin/app.js", "/%61dmin/app.js", "//admin/app.js",
                     "/x/../admin/app.js", "/admin/./app.js", "/admin%2Fapp.js"):
            status, headers, data = self.call(path)
            self.assertEqual(status, 302, path)
            self.assertIn("/?login=1&next=", headers["Location"], path)
            self.assertEqual(data, b"", path)

    def test_head_is_locked_too(self):
        for path in ("/admin/app.js", "/%61dmin/app.js"):
            self.assertEqual(self.call(path, "HEAD")[0], 302, path)

    def test_old_paths_no_longer_serve_the_owner_page(self):
        self.assertEqual(self.call("/app.js")[0], 404)

    def test_admin_apis_refuse(self):
        for path in ("/api/attention", "/api/attention?demo=urgent", "/api/arrivals", "/api/prom/query?query=up",
                     "/api/news?topic=opened", "/api/news?topic=all&topic=opened"):
            status, _, _ = self.call(path)
            self.assertEqual(status, 401, path)

    def test_admin_writes_refuse(self):
        for path in ("/api/attention/x/ack", "/api/attention/x/dismiss", "/api/news/x/open"):
            self.assertEqual(self.call(path, "POST")[0], 401, path)

    def test_news_is_public_without_feed_errors(self):
        server.LATEST["news_errors"] = ["http://private.example failed"]
        status, _, data = self.call("/api/news?topic=all")
        self.assertEqual(status, 200)
        self.assertNotIn("errors", json.loads(data))
        self.assertNotIn(b"private.example", data)

    def test_summary_contains_nothing_technical(self):
        now = time.time()
        server.LATEST["inputs"] = {
            "kuma": {"AdGuard": 1}, "restarts": {},
            "netwatch": {"items": [{"ip": "203.0.113.7", "flag": ["bad"], "scope": "internet", "dir": "in", "live": True, "last": now}]},
            "prom": {"md_active": 2, "md_required": 2, "smart_status": {"sda": 1}, "drive_temp": {"sda": 35}, "free_ratio": 0.5, "free_bytes": 3.2e12, "speed_last": 9e8, "speed_median": 9e8}}
        server.LATEST["inputs_at"] = now
        server.LATEST["arrivals"] = {"arrived": [{"show": "Some.Movie.2024", "ep": "", "at": now, "known": False},
                                                 {"show": "Example Show", "ep": "E05", "at": now, "known": True}],
                                     "downloading": []}
        status, _, data = self.call("/api/public/summary")
        self.assertEqual(status, 200)
        d = json.loads(data)
        self.assertEqual(d["status"]["title"], "Everything's running")
        self.assertEqual((d["free_bytes"], d["internet_bps"], d["downloads"]["other"]), (3.2e12, 9e8, 1))
        self.assertEqual(d["downloads"]["arrived"][0]["show"], "Example Show")
        self.assertNotIn(b"203.0.113.7", data)
        self.assertNotIn(b"Some.Movie", data)

    def test_summary_demo_overrides_only_the_status(self):
        d = json.loads(self.call("/api/public/summary?demo=slow")[2])
        self.assertEqual(d["status"]["title"], "Internet is slow right now")
        self.assertEqual(self.call("/api/public/summary?demo=nope")[0], 200)


class AdminRoutes(Base):
    def test_landing_goes_to_the_owner_page(self):
        status, headers, _ = self.call("/", cookie=self.cookie())
        self.assertEqual((status, headers["Location"]), (302, "/admin/"))
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_landing_ignores_next_so_ports_cannot_bounce_forever(self):
        # we only get here with ?login=1 when another port just refused this cookie: sending it back would loop
        target = urllib.parse.quote(f"http://{HOST}:8800/x", safe="")
        for query in (f"?login=1&next={target}", f"?next={target}", "?next=http%3A%2F%2Fevil.example%2F"):
            self.assertEqual(self.call(f"/{query}", cookie=self.cookie())[1]["Location"], "/admin/", query)

    def test_bare_admin_gets_its_slash(self):
        status, headers, _ = self.call("/admin", cookie=self.cookie())
        self.assertEqual((status, headers["Location"]), (302, "/admin/"))

    def test_owner_page_and_apis_open(self):
        for path in ("/admin/", "/admin/app.js", "/api/attention", "/api/arrivals", "/api/news?topic=opened"):
            self.assertEqual(self.call(path, cookie=self.cookie())[0], 200, path)

    def test_admin_news_keeps_feed_errors(self):
        self.assertIn("errors", json.loads(self.call("/api/news?topic=all", cookie=self.cookie())[2]))

    def test_expired_cookie_counts_as_logged_out(self):
        expired = self.cookie(time.time() - 1)
        self.assertEqual(self.call("/api/attention", cookie=expired)[0], 401)
        self.assertEqual(self.call("/", cookie=expired)[0], 200)


class Login(Base):
    def test_right_password_sets_the_cookie(self):
        status, headers, data = self.login()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"ok": True, "next": "/admin/"})
        cookie = headers["Set-Cookie"]
        for part in ("nas_admin=", "HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=2592000"):
            self.assertIn(part, cookie)
        self.assertEqual(self.call("/api/attention", cookie=cookie.split(";")[0])[0], 200)

    def test_without_remember_there_is_no_max_age(self):
        self.assertNotIn("Max-Age", self.login(remember=False)[1]["Set-Cookie"])

    def test_wrong_password(self):
        status, headers, data = self.login("nope")
        self.assertEqual((status, json.loads(data)["error"]), (401, "wrong"))
        self.assertNotIn("Set-Cookie", headers)

    def test_sixth_attempt_must_wait_even_with_the_right_password(self):
        for _ in range(5):
            self.assertEqual(self.login("nope")[0], 401)
        status, headers, data = self.login()
        self.assertEqual(status, 429)
        d = json.loads(data)
        self.assertEqual(d["error"], "wait")
        self.assertGreater(d["retry_after"], 0)
        self.assertNotIn("Set-Cookie", headers)

    def test_success_clears_the_count(self):
        for _ in range(4):
            self.login("nope")
        self.assertEqual(self.login()[0], 200)
        for _ in range(4):
            self.assertEqual(self.login("nope")[0], 401)

    def test_evil_next_falls_back(self):
        self.assertEqual(json.loads(self.login(next_url="http://evil.example/")[2])["next"], "/admin/")

    def test_good_next_is_returned(self):
        url = f"http://{HOST}:8800/"
        self.assertEqual(json.loads(self.login(next_url=url)[2])["next"], url)

    def test_bad_bodies_are_refused(self):
        for body in ("", "not json", "[]", '{"pw": 5}', '{"remember": true}'):
            self.assertEqual(self.call("/api/login", "POST", body=body)[0], 400, body)

    def test_huge_body_is_refused(self):
        self.assertEqual(self.call("/api/login", "POST", body="x" * 5000)[0], 413)

    def test_logout_clears_the_cookie(self):
        status, headers, _ = self.call("/api/logout", "POST", cookie=self.cookie())
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])


class NotConfigured(unittest.TestCase):
    """Missing settings: login refused, locked routes stay locked, guests unaffected."""

    @classmethod
    def setUpClass(cls):
        remove_auth()
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, method="GET", body=None, cookie=None):
        c = http.client.HTTPConnection(HOST, self.port, timeout=10)
        c.request(method, path, body=body, headers={"Cookie": cookie} if cookie else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_login_says_not_configured(self):
        status, data = self.call("/api/login", "POST", json.dumps({"pw": "x"}))
        self.assertEqual((status, json.loads(data)["error"]), (503, "not_configured"))

    def test_guest_page_still_works(self):
        self.assertEqual(self.call("/")[0], 200)
        self.assertEqual(self.call("/api/public/summary")[0], 200)

    def test_everything_else_stays_locked_even_with_a_token_signed_by_an_empty_key(self):
        forged = f"nas_admin={auth.make_token('', time.time() + 60)}"
        self.assertEqual(self.call("/api/attention", cookie=forged)[0], 401)
        self.assertEqual(self.call("/admin/", cookie=forged)[0], 302)


if __name__ == "__main__":
    unittest.main()
