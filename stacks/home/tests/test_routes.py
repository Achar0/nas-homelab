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
        if body is not None:
            headers["Content-Type"] = "application/json"
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

    def test_iptv_playlist_is_public(self):
        self.addCleanup(server.LATEST.__setitem__, "iptv", server.LATEST["iptv"])
        server.LATEST["iptv"] = {**server.LATEST["iptv"], "playlist": "#EXTM3U\n#EXTINF:-1,A\nhttp://a/1\n"}
        status, _, data = self.call("/iptv.m3u")
        self.assertEqual((status, data), (200, b"#EXTM3U\n#EXTINF:-1,A\nhttp://a/1\n"))

    def test_iptv_playlist_before_the_first_check(self):
        self.addCleanup(server.LATEST.__setitem__, "iptv", server.LATEST["iptv"])
        server.LATEST["iptv"] = {**server.LATEST["iptv"], "playlist": ""}
        self.assertEqual(self.call("/iptv.m3u")[0], 404)

    def test_iptv_status_needs_the_login(self):
        self.assertIn(self.call("/api/iptv")[0], (302, 401))

    def test_tv_page_is_public(self):
        status, _, data = self.call("/tv")
        self.assertEqual(status, 200)
        self.assertIn(b'lang="zh-CN"', data)

    def test_tv_data_contains_nothing_technical(self):
        now = time.time()
        server.LATEST["inputs"] = {
            "kuma": {"AdGuard": 1}, "restarts": {},
            "netwatch": {"items": [{"ip": "203.0.113.7", "flag": ["bad"], "scope": "internet", "dir": "in", "live": True, "last": now}]},
            "prom": {"md_active": 2, "md_required": 2, "smart_status": {"sda": 1}, "drive_temp": {"sda": 35}, "free_ratio": 0.5, "free_bytes": 3.2e12, "speed_last": 9e8, "speed_median": 9e8}}
        server.LATEST["inputs_at"] = now
        server.LATEST["arrivals"] = {"arrived": [{"show": "Some.Movie.2024", "ep": "", "at": now, "known": False},
                                                 {"show": "Example Show", "ep": "E05", "at": now, "known": True}],
                                     "downloading": []}
        status, _, data = self.call("/api/public/tv")
        self.assertEqual(status, 200)
        self.assertIn(b"Example Show", json.dumps(json.loads(data)).encode())
        for secret in (b"203.0.113.7", b"Some.Movie", b"free_bytes", b"internet_bps"):
            self.assertNotIn(secret, data)

    def test_tv_data_at_first_boot(self):
        saved = {k: server.LATEST[k] for k in ("inputs", "inputs_at", "arrivals", "weather")}
        self.addCleanup(server.LATEST.update, saved)
        server.LATEST.update(inputs=None, inputs_at=0, arrivals={"arrived": [], "downloading": []}, weather=None)
        d = json.loads(self.call("/api/public/tv")[2])
        self.assertEqual((d["status"], d["weather"], d["episodes"]), (None, None, []))

    def test_tv_demo_overrides_only_the_status(self):
        self.assertEqual(json.loads(self.call("/api/public/tv?demo=slow")[2])["status"]["zh"], "网络有点慢")
        self.assertIsNone(json.loads(self.call("/api/public/tv?demo=unknown")[2])["status"])
        self.assertEqual(self.call("/api/public/tv?demo=nope")[0], 200)


class AdminRoutes(Base):
    IPTV_LIST = "#EXTM3U\n#EXTINF:-1,A\nhttp://a.example/1\n"

    def fresh_iptv(self):
        self.addCleanup(server.LATEST.__setitem__, "iptv", server.LATEST["iptv"])
        server.LATEST["iptv"] = {"lists": [], "playlist": "", "counts": None, "checked": 0, "checking": False}

    def iptv_post(self, path, obj=None):
        return self.call(path, "POST", cookie=self.cookie(), body=json.dumps(obj or {}))

    def iptv_lists(self):
        return json.loads(self.call("/api/iptv", cookie=self.cookie())[2])["lists"]

    def test_iptv_add_by_address(self):
        self.fresh_iptv()
        self.assertEqual(self.iptv_post("/api/iptv/lists", {"url": "https://example.org/a.m3u8", "name": "A"})[0], 200)
        self.assertEqual([(x["name"], x["kind"]) for x in self.iptv_lists()], [("A", "url")])

    def test_iptv_refuses_a_bad_address(self):
        self.fresh_iptv()
        self.assertEqual(self.iptv_post("/api/iptv/lists", {"url": "file:///etc/passwd"})[0], 400)

    def test_iptv_refuses_the_same_address_twice(self):
        self.fresh_iptv()
        self.iptv_post("/api/iptv/lists", {"url": "https://example.org/a.m3u8"})
        self.assertEqual(self.iptv_post("/api/iptv/lists", {"url": "https://example.org/a.m3u8"})[0], 409)

    def test_iptv_upload_a_file(self):
        self.fresh_iptv()
        self.assertEqual(self.iptv_post("/api/iptv/upload", {"name": "mine.m3u", "content": self.IPTV_LIST})[0], 200)
        lst = self.iptv_lists()[0]
        self.assertEqual((lst["name"], lst["kind"]), ("mine.m3u", "file"))
        self.assertTrue(os.path.exists(server.iptv_file(lst["id"])))

    def test_iptv_upload_must_be_a_playlist(self):
        self.fresh_iptv()
        self.assertEqual(self.iptv_post("/api/iptv/upload", {"name": "x", "content": "<html>"})[0], 400)

    def test_iptv_delete_removes_list_file_and_channels(self):
        self.fresh_iptv()
        self.iptv_post("/api/iptv/upload", {"name": "mine.m3u", "content": self.IPTV_LIST})
        lst = self.iptv_lists()[0]
        self.assertEqual(self.iptv_post(f"/api/iptv/lists/{lst['id']}/delete")[0], 200)
        self.assertEqual(self.iptv_lists(), [])
        self.assertFalse(os.path.exists(server.iptv_file(lst["id"])))

    def test_iptv_delete_unknown_is_404(self):
        self.fresh_iptv()
        self.assertEqual(self.iptv_post("/api/iptv/lists/nope/delete")[0], 404)

    def test_iptv_channels_of_a_list(self):
        self.fresh_iptv()
        server.LATEST["iptv"]["lists"] = [{"id": "x1", "name": "n", "kind": "url", "url": "http://e", "checked": 1, "error": "",
                                          "rows": [{"info": "#EXTINF:-1,A", "url": "http://a/1", "opts": [], "state": "lag"}]}]
        status, _, data = self.call("/api/iptv/channels?id=x1", cookie=self.cookie())
        self.assertEqual((status, json.loads(data)["channels"][0]["state"]), (200, "lag"))
        self.assertEqual(self.call("/api/iptv/channels?id=nope", cookie=self.cookie())[0], 404)

    def test_iptv_check_now(self):
        self.fresh_iptv()
        self.assertEqual(self.iptv_post("/api/iptv/check")[0], 200)

    def test_iptv_changes_need_the_login(self):
        for path in ("/api/iptv/lists", "/api/iptv/upload", "/api/iptv/check", "/api/iptv/lists/x/delete"):
            self.assertEqual(self.call(path, "POST", body="{}")[0], 401, path)

    def test_iptv_page_needs_the_login(self):
        self.assertEqual(self.call("/admin/iptv.html")[0], 302)
        self.assertEqual(self.call("/admin/iptv.html", cookie=self.cookie())[0], 200)

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


class SettingsPage(Base):
    def test_settings_page_needs_login(self):
        for path in ("/admin/settings", "/admin/settings/", "/admin/settings.html", "/admin/settings.js", "/admin/settings.css",
                     "/%61dmin/settings", "/x/../admin/settings.html"):
            status, headers, data = self.call(path)
            self.assertEqual(status, 302, path)
            self.assertIn("/?login=1&next=", headers["Location"], path)
            self.assertEqual(data, b"", path)

    def test_settings_page_served_when_logged_in(self):
        for path in ("/admin/settings", "/admin/settings/"):
            status, _, data = self.call(path, cookie=self.cookie())
            self.assertEqual(status, 200, path)
            self.assertIn(b"settings.js", data)
        self.assertEqual(self.call("/admin/settings.js", cookie=self.cookie())[0], 200)

    def test_admin_page_links_to_settings(self):
        self.assertIn(b'href="/admin/settings"', self.call("/admin/", cookie=self.cookie())[2])


class Account(Base):
    def setUp(self):
        super().setUp()
        write_auth(PW_HASH, KEY)
        self.addCleanup(write_auth, PW_HASH, KEY)
        real = auth.save
        self.addCleanup(setattr, auth, "save", real)

    def change(self, cookie, current=PW, new="a new password"):
        return self.call("/api/account/password", "POST", cookie=cookie, body=json.dumps({"current": current, "new": new}))

    def ok(self, cookie):
        return self.call("/api/attention", cookie=cookie)[0] == 200

    def test_account_routes_need_login(self):
        self.assertEqual(self.change(None)[0], 401)
        self.assertEqual(self.call("/api/account/logout-everywhere", "POST", body="{}")[0], 401)
        self.assertTrue(auth.login_ok(PW))

    def test_change_keeps_this_session_and_ends_others(self):
        a, b = self.cookie(), self.cookie()
        status, headers, _ = self.change(a)
        self.assertEqual(status, 200)
        new_cookie = headers["Set-Cookie"].split(";")[0]
        self.assertTrue(self.ok(new_cookie))
        self.assertFalse(self.ok(b))
        self.assertTrue(auth.login_ok("a new password"))
        self.assertFalse(auth.login_ok(PW))

    def test_change_keeps_remember_setting(self):
        short = self.cookie()   # expires in 60 s, so not "remember"
        self.assertNotIn("Max-Age", self.change(short)[1]["Set-Cookie"])
        write_auth(PW_HASH, KEY)
        long = self.cookie(time.time() + 20 * 86400)
        self.assertIn("Max-Age=2592000", self.change(long)[1]["Set-Cookie"])

    def test_wrong_current_is_throttled_like_login(self):
        cookie = self.cookie()
        for _ in range(5):
            status, _, data = self.change(cookie, current="wrong")
            self.assertEqual(status, 403)
        status, _, data = self.change(cookie, current="wrong")
        self.assertEqual(status, 429)
        self.assertIn("retry_after", json.loads(data))
        self.assertEqual(self.change(cookie)[0], 429)   # even with the right one, until the wait is over
        self.assertTrue(auth.login_ok(PW))

    def test_short_new_password_400(self):
        self.assertEqual(self.change(self.cookie(), new="short")[0], 400)
        self.assertTrue(auth.login_ok(PW))

    def test_wrong_types_400(self):
        status, _, _ = self.call("/api/account/password", "POST", cookie=self.cookie(), body=json.dumps({"current": 1, "new": 2}))
        self.assertEqual(status, 400)

    def test_logout_everywhere_ends_this_session_too(self):
        cookie = self.cookie()
        status, headers, _ = self.call("/api/account/logout-everywhere", "POST", cookie=cookie, body="{}")
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertFalse(self.ok(cookie))
        self.assertTrue(auth.login_ok(PW))

    def test_read_only_or_missing_auth_file_says_so(self):
        auth.save = lambda *a: (_ for _ in ()).throw(OSError("read-only"))
        self.assertEqual(self.change(self.cookie())[0], 503)
        self.assertEqual(self.call("/api/account/logout-everywhere", "POST", cookie=self.cookie(), body="{}")[0], 503)
        self.assertTrue(auth.login_ok(PW))


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
