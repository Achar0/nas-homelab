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


class ServicesBase(Base):
    def new_container(self, name="thing-9000", ports=(), state="running"):
        server.STORE.update(lambda s: s.update(known_containers=[]))
        c = {"Names": [f"/{name}"], "State": state,
             "Ports": [{"IP": "0.0.0.0", "PublicPort": p, "PrivatePort": p} for p in ports]}
        server.scan_containers([c])
        return f"c-{name}"

    def service(self, sid):
        return next(s for s in server.STORE.get()["services"] if s["id"] == sid)

    def set(self, sid, **body):
        return self.post(f"/api/settings/services/{sid}", body)


class Alerts(ServicesBase):
    def test_alert_saved(self):
        self.assertEqual(self.post("/api/settings/alerts", {"hot_c": 60, "push": False})[0], 200)
        a = server.STORE.get()["alerts"]
        self.assertEqual((a["hot_c"], a["push"], a["free_pct"]), (60, False, 15))

    def test_alert_out_of_range_400(self):
        for body in ({"hot_c": 71}, {"free_pct": "20"}, {"push": 1}, {"nonsense": 1}):
            self.assertEqual(self.post("/api/settings/alerts", body)[0], 400, body)
        self.assertEqual(server.STORE.get()["alerts"]["hot_c"], 50)

    def test_writes_survive_restart(self):
        self.post("/api/settings/alerts", {"hot_c": 60})
        self.assertEqual(settings.Store(self.path, self.feeds_path).get()["alerts"]["hot_c"], 60)


class Services(ServicesBase):
    def test_needs_login(self):
        for path in ("/api/settings/alerts", "/api/settings/services/home", "/api/settings/order", "/api/settings/show"):
            self.assertEqual(self.post(path, login=False)[0], 401, path)

    def test_unknown_service_404(self):
        self.assertEqual(self.set("nope", on_dock=True)[0], 404)

    def test_bad_ports_refused(self):
        sid = self.new_container()
        for port in ("8080/evil", 0, 70000, True, 80.5):
            self.assertEqual(self.set(sid, port=port)[0], 400, port)
        self.assertEqual(self.service(sid)["port"], 9000)

    def test_cannot_dock_without_a_port(self):
        sid = self.new_container("thing")
        self.assertEqual(self.set(sid, on_dock=True)[0], 400)
        self.assertEqual(self.set(sid, port=9000)[0], 200)
        self.assertEqual(self.set(sid, on_dock=True)[0], 200)

    def test_docking_moves_new_to_known(self):
        sid = self.new_container()
        self.assertEqual(self.set(sid, on_dock=True)[0], 200)
        s = self.service(sid)
        self.assertEqual((s["on_dock"], s["state"]), (True, "known"))

    def test_typing_a_port_keeps_it_under_new(self):
        sid = self.new_container("thing")
        self.set(sid, port=9000)
        self.assertEqual(self.service(sid)["state"], "new")

    def test_name_limited_and_kept_as_plain_text(self):
        sid = self.new_container()
        self.assertEqual(self.set(sid, name="x" * 41)[0], 400)
        self.assertEqual(self.set(sid, name="   ")[0], 400)
        self.assertEqual(self.set(sid, name=5)[0], 400)
        self.assertEqual(self.set(sid, name=" <b>Mine</b> ")[0], 200)
        self.assertEqual(self.service(sid)["name"], "<b>Mine</b>")
        self.assertEqual(self.service(sid)["container"], "thing-9000")

    def test_ignore_hides_only_new_rows(self):
        self.assertEqual(self.post("/api/settings/services/adguard/ignore")[0], 400)
        sid = self.new_container()
        self.assertEqual(self.post(f"/api/settings/services/{sid}/ignore")[0], 200)
        self.assertEqual(self.service(sid)["state"], "ignored")

    def test_remove_only_when_not_running(self):
        sid = self.new_container()
        self.assertEqual(self.post(f"/api/settings/services/{sid}/remove")[0], 400)
        server.scan_containers([])
        self.assertEqual(self.post(f"/api/settings/services/{sid}/remove")[0], 200)
        self.assertFalse(any(s["id"] == sid for s in server.STORE.get()["services"]))


class Order(ServicesBase):
    def known_ids(self):
        return [s["id"] for s in server.STORE.get()["services"] if s["state"] == "known"]

    def test_dock_order(self):
        ids = list(reversed(self.known_ids()))
        self.assertEqual(self.post("/api/settings/order", {"list": "dock", "ids": ids})[0], 200)
        self.assertEqual(self.known_ids(), ids)

    def test_order_must_be_a_permutation(self):
        ids = self.known_ids()
        before = server.STORE.get()
        for bad in (ids[:-1], ids + ["nope"], ids[:-1] + [ids[0]], "x", None):
            self.assertEqual(self.post("/api/settings/order", {"list": "dock", "ids": bad})[0], 400, bad)
        self.assertEqual(self.post("/api/settings/order", {"list": "nope", "ids": ids})[0], 400)
        self.assertEqual(server.STORE.get(), before)

    def test_order_keeps_new_rows_after_known(self):
        sid = self.new_container()
        ids = list(reversed(self.known_ids()))
        self.assertEqual(self.post("/api/settings/order", {"list": "dock", "ids": ids})[0], 200)
        self.assertEqual([s["id"] for s in server.STORE.get()["services"]], ids + [sid])

    def test_rail_and_cards_order(self):
        self.assertEqual(self.post("/api/settings/order", {"list": "rail_nas", "ids": ["free", "temperature", "memory", "cpu"]})[0], 200)
        self.assertEqual(server.STORE.get()["rail"]["nas"][0]["id"], "free")
        self.assertEqual(self.post("/api/settings/order", {"list": "cards", "ids": ["connections", "tailscale", "speedtest", "adguard", "qbittorrent"]})[0], 200)
        self.assertEqual(server.STORE.get()["cards"][0]["id"], "connections")

    def test_show(self):
        self.assertEqual(self.post("/api/settings/show", {"list": "cards", "id": "tailscale", "show": False})[0], 200)
        self.assertFalse(next(c for c in server.STORE.get()["cards"] if c["id"] == "tailscale")["show"])
        self.assertEqual(self.post("/api/settings/show", {"list": "rail_services", "id": "adguard", "show": False})[0], 200)

    def test_show_refused(self):
        for body in ({"list": "dock", "id": "home", "show": False}, {"list": "cards", "id": "nope", "show": False},
                     {"list": "cards", "id": "tailscale", "show": "no"}):
            self.assertEqual(self.post("/api/settings/show", body)[0], 400, body)


class Layout(ServicesBase):
    def test_layout_needs_login(self):
        self.assertEqual(self.req("GET", "/api/layout", login=False)[0], 401)

    def test_layout_for_the_owner(self):
        data = self.req("GET", "/api/layout")[1]
        self.assertEqual(data["dock"][0], {"id": "home", "name": "Home", "icon": "mdi-home.svg", "mono": True, "port": 3001, "scheme": "http"})
        self.assertNotIn("firefox", [d["id"] for d in data["dock"]])
        self.assertIs(data["push"], True)

    def test_internal_layout_open_to_this_machine_without_login(self):
        code, data = self.req("GET", "/api/internal/layout", login=False)
        self.assertEqual(code, 200)
        self.assertIn("dock", data)

    def test_internal_layout_refuses_non_loopback(self):
        real = server.LOOPBACK
        server.LOOPBACK = set()
        self.addCleanup(setattr, server, "LOOPBACK", real)
        self.assertEqual(self.req("GET", "/api/internal/layout", login=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/internal/layout", login=True)[0], 401)

    def test_internal_layout_carries_no_private_fields(self):
        raw = json.dumps(self.req("GET", "/api/internal/layout", login=False)[1])
        for word in ("url", "known_containers", "container", "feeds", "alerts", "seed.example"):
            self.assertNotIn(word, raw)

    def test_new_row_stays_off_the_dock_until_switched_on(self):
        sid = self.new_container()
        self.assertNotIn(sid, [d["id"] for d in self.req("GET", "/api/layout")[1]["dock"]])
        self.set(sid, on_dock=True)
        self.assertIn(sid, [d["id"] for d in self.req("GET", "/api/layout")[1]["dock"]])
