"""Settings API against a real server: login, feeds, services, order and layout."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["NTFY_URL"] = ""
import auth  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402

KEY = "k" * 64
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
RSS = open(os.path.join(FIXTURES, "rss_sample.xml"), "rb").read()
HTML_PAGE = b"<html><body><p>Private page text</p></body></html>"


def rss(title):
    return f'<rss version="2.0"><channel><title>{title}</title></channel></rss>'.encode()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.environ["ADMIN_AUTH_FILE"] = os.path.join(cls.dir, "auth.json")
        with open(os.environ["ADMIN_AUTH_FILE"], "w") as f:
            json.dump({"hash": auth.hash_password("correct horse"), "key": KEY}, f)
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.dir)

    def setUp(self):
        real_store, real_get = server.STORE, server.get_limited
        self.addCleanup(setattr, server, "STORE", real_store)
        self.addCleanup(setattr, server, "get_limited", real_get)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        feeds = os.path.join(folder, "feeds.json")
        with open(feeds, "w") as f:
            json.dump([{"name": "Seed", "url": "https://seed.example/feed", "topic": "tech", "lang": "en"}], f)
        self.path, self.feeds_path = os.path.join(folder, "settings.json"), feeds
        server.STORE = settings.Store(self.path, feeds)
        server.FEEDS_WAKE.clear()

    def req(self, method, path, body=None, login=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Content-Type": "application/json"}
        if login:
            headers["Cookie"] = f"nas_admin={auth.make_token(KEY, time.time() + 60)}"
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    def post(self, path, body=None, login=True):
        return self.req("POST", path, {} if body is None else body, login)

    def feed_urls(self):
        return [f["url"] for f in server.STORE.get()["feeds"]]

    def fetches(self, data):
        server.get_limited = lambda url: data

    def add(self, url="https://new.example/rss", topic="markets", lang="it"):
        return self.post("/api/settings/feeds", {"url": url, "topic": topic, "lang": lang})


class Login(Base):
    def test_settings_api_needs_login(self):
        self.assertEqual(self.req("GET", "/api/settings", login=False)[0], 401)
        for path in ("/api/settings/feeds", "/api/settings/feeds/x", "/api/settings/feeds/x/remove"):
            self.assertEqual(self.post(path, login=False)[0], 401, path)
        self.assertEqual(self.feed_urls(), ["https://seed.example/feed"])

    def test_get_settings_hides_internal_fields(self):
        code, data = self.req("GET", "/api/settings")
        self.assertEqual(code, 200)
        self.assertEqual(data["feeds"][0]["name"], "Seed")
        self.assertNotIn("known_containers", data)
        self.assertIsNone(data["problem"])

    def test_get_settings_reports_a_problem(self):
        with open(self.path, "w") as f:
            f.write("{nope")
        server.STORE = settings.Store(self.path, self.feeds_path)
        self.assertTrue(self.req("GET", "/api/settings")[1]["problem"])

    def test_oversized_body_refused(self):
        code, _ = self.post("/api/settings/feeds", {"url": "x" * (server.SETTINGS_BODY_LIMIT + 1)})
        self.assertEqual(code, 413)


class AddFeed(Base):
    def test_add_feed_uses_its_title(self):
        self.fetches(rss("New Feed"))
        code, data = self.add()
        self.assertEqual(code, 200, data)
        f = server.STORE.get()["feeds"][-1]
        self.assertEqual((f["name"], f["topic"], f["lang"], f["enabled"]), ("New Feed", "markets", "it", True))
        self.assertTrue(server.FEEDS_WAKE.is_set())

    def test_add_feed_falls_back_to_hostname(self):
        self.fetches(b'<rss version="2.0"><channel></channel></rss>')
        self.assertEqual(self.add("https://www.new.example/rss")[0], 200)
        self.assertEqual(server.STORE.get()["feeds"][-1]["name"], "new.example")

    def test_add_real_fixture(self):
        self.fetches(RSS)
        self.assertEqual(self.add()[0], 200)

    def test_add_refuses_html_page(self):
        self.fetches(HTML_PAGE)
        code, data = self.add()
        self.assertEqual(code, 400)
        self.assertNotIn("Private page text", json.dumps(data))
        self.assertEqual(len(self.feed_urls()), 1)

    def test_add_refuses_timeout_and_oversize(self):
        for err in (TimeoutError("slow"), ValueError("https://new.example: larger than 5 bytes"), OSError("refused")):
            def fail(url, e=err):
                raise e
            server.get_limited = fail
            code, data = self.add()
            self.assertEqual(code, 400)
            self.assertEqual(data["error"], "Couldn't read that address.")
            self.assertEqual(len(self.feed_urls()), 1)

    def test_add_refuses_duplicate_and_ftp(self):
        def never(url):
            raise AssertionError("must not fetch")
        server.get_limited = never
        self.assertEqual(self.add("https://seed.example/feed")[0], 400)
        for url in ("ftp://new.example/rss", "file:///etc/passwd", "", 5):
            self.assertEqual(self.add(url)[0], 400, url)
        self.assertEqual(self.add(topic="sport")[0], 400)
        self.assertEqual(self.add(lang="fr")[0], 400)

    def test_add_cleans_hostile_title(self):
        self.fetches(rss("&lt;script&gt;x&lt;/script&gt;Name"))
        self.assertEqual(self.add()[0], 200)
        self.assertNotIn("<", server.STORE.get()["feeds"][-1]["name"])

    def test_long_title_is_cut(self):
        self.fetches(rss("T" * 500))
        self.assertEqual(self.add()[0], 200)
        self.assertLessEqual(len(server.STORE.get()["feeds"][-1]["name"]), 80)


class ChangeFeed(Base):
    def seed_id(self):
        return server.STORE.get()["feeds"][0]["id"]

    def test_disabled_feed_is_not_fetched_and_wakes_refresh(self):
        fetched = []
        server.get_limited = lambda url: fetched.append(url) or rss("x")
        self.assertEqual(self.post(f"/api/settings/feeds/{self.seed_id()}", {"enabled": False})[0], 200)
        self.assertTrue(server.FEEDS_WAKE.is_set())
        server.feeds_tick()
        self.assertEqual(fetched, [])
        self.post(f"/api/settings/feeds/{self.seed_id()}", {"enabled": True})
        server.feeds_tick()
        self.assertEqual(fetched, ["https://seed.example/feed"])

    def test_enabled_must_be_true_or_false(self):
        self.assertEqual(self.post(f"/api/settings/feeds/{self.seed_id()}", {"enabled": "no"})[0], 400)

    def test_unknown_feed_404(self):
        self.assertEqual(self.post("/api/settings/feeds/nope", {"enabled": False})[0], 404)
        self.assertEqual(self.post("/api/settings/feeds/nope/remove")[0], 404)

    def test_remove_feed(self):
        self.assertEqual(self.post(f"/api/settings/feeds/{self.seed_id()}/remove")[0], 200)
        self.assertEqual(self.feed_urls(), [])
        self.assertTrue(server.FEEDS_WAKE.is_set())

    def test_write_failure_says_so(self):
        real = settings.os.replace
        settings.os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        self.addCleanup(setattr, settings.os, "replace", real)
        code, data = self.post(f"/api/settings/feeds/{self.seed_id()}", {"enabled": False})
        self.assertEqual(code, 503)
        self.assertNotIn("disk full", json.dumps(data))
        self.assertTrue(server.STORE.get()["feeds"][0]["enabled"])


class Scan(Base):
    def gather(self, containers):
        return lambda now: ({"containers": containers}, [])

    def test_tick_records_a_new_container(self):
        c = {"Names": ["/thing-9000"], "State": "running", "Ports": []}
        server.attention_tick(self.gather([]))
        server.attention_tick(self.gather([c]))
        self.assertEqual(server.STORE.get()["services"][-1]["container"], "thing-9000")

    def test_tick_with_docker_unreadable_changes_nothing(self):
        server.attention_tick(self.gather([]))
        before = server.STORE.get()
        server.attention_tick(self.gather(None))
        self.assertEqual(server.STORE.get(), before)

    def test_write_failure_does_not_stop_the_tick(self):
        real = settings.os.replace
        settings.os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        self.addCleanup(setattr, settings.os, "replace", real)
        real_save = server.save_state
        server.save_state = lambda: None
        self.addCleanup(setattr, server, "save_state", real_save)
        server.attention_tick(self.gather([]))   # must not raise

    def test_gather_passes_the_same_listing_to_restarts(self):
        listing = [{"Id": "abc", "Names": ["/thing"], "State": "running"}]
        real_get = server.get
        self.addCleanup(setattr, server, "get", real_get)

        def fake(url, *a, **kw):
            if url.endswith("/containers/json?all=1"):
                return json.dumps(listing).encode()
            if url.endswith("/containers/abc/json"):
                return b'{"RestartCount": 0}'
            raise OSError("not available")
        server.get = fake
        inputs, _ = server.gather_inputs(1000)
        self.assertEqual(inputs["containers"], listing)
        self.assertEqual(inputs["restarts"], {"thing": 0})

    def test_gather_with_docker_down(self):
        real_get = server.get
        self.addCleanup(setattr, server, "get", real_get)

        def fake(*a, **kw):
            raise OSError("not available")
        server.get = fake
        inputs, down = server.gather_inputs(1000)
        self.assertIsNone(inputs["containers"])
        self.assertIsNone(inputs["restarts"])
        self.assertIn("restarts", down)
