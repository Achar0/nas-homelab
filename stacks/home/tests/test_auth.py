import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import auth  # noqa: E402

AUTH_FILE = os.path.join(tempfile.mkdtemp(), "auth.json")
KEY = "k" * 64
HOST = "192.168.1.14"


class Passwords(unittest.TestCase):
    def test_round_trip(self):
        stored = auth.hash_password("correct horse")
        self.assertTrue(auth.verify_password("correct horse", stored))
        self.assertFalse(auth.verify_password("wrong", stored))

    def test_hash_has_no_dollar_because_compose_interpolates_it(self):
        self.assertNotIn("$", auth.hash_password("x"))

    def test_same_password_gets_a_different_salt(self):
        self.assertNotEqual(auth.hash_password("x"), auth.hash_password("x"))

    def test_malformed_hash_is_refused_without_error(self):
        for bad in ("", "nonsense", "scrypt:1:2", "scrypt:a:b:c:d:e", "md5:1:1:1:aa:bb", "scrypt:32768:8:1:zz:zz", None):
            self.assertFalse(auth.verify_password("x", bad), bad)


class Tokens(unittest.TestCase):
    def test_valid_until_expiry(self):
        tok = auth.make_token(KEY, 1000)
        self.assertTrue(auth.check_token(KEY, tok, 999))
        self.assertFalse(auth.check_token(KEY, tok, 1000))

    def test_tampered_expiry_is_refused(self):
        tok = auth.make_token(KEY, 1000)
        sig = tok.split(".")[1]
        self.assertFalse(auth.check_token(KEY, f"9999999999.{sig}", 999))

    def test_old_key_is_refused(self):
        self.assertFalse(auth.check_token("o" * 64, auth.make_token(KEY, 1000), 999))

    def test_garbage_is_refused_without_error(self):
        for bad in ("", ".", "abc", "abc.def", "1.2.3", "é.é", None):
            self.assertFalse(auth.check_token(KEY, bad, 0), bad)


class Session(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ("SESSION_SECRET", "ADMIN_PASSWORD_HASH", "ADMIN_AUTH_FILE")}
        os.environ["ADMIN_AUTH_FILE"] = AUTH_FILE
        self.clear()

    def tearDown(self):
        self.clear()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def clear(self):
        if os.path.exists(AUTH_FILE):
            os.remove(AUTH_FILE)

    def write(self, pw_hash, key):
        with open(AUTH_FILE, "w") as f:
            json.dump({"hash": pw_hash, "key": key}, f)

    def set_up_env(self, key=KEY):
        self.write(auth.hash_password("pw"), key)

    def test_missing_file_refuses_everything(self):
        self.assertFalse(auth.configured())
        self.assertFalse(auth.login_ok("pw"))
        self.assertFalse(auth.session_ok(f"nas_admin={auth.make_token(KEY, 1000)}", 0))

    def test_invalid_json_refuses_even_with_env_values(self):
        os.environ["ADMIN_PASSWORD_HASH"] = auth.hash_password("pw")
        os.environ["SESSION_SECRET"] = KEY
        with open(AUTH_FILE, "w") as f:
            f.write("{not json")
        self.assertFalse(auth.login_ok("pw"))
        self.assertFalse(auth.session_ok(f"nas_admin={auth.make_token(KEY, 1000)}", 0))

    def test_json_of_the_wrong_shape_refuses(self):
        for raw in ('[1]', '{"hash": 1, "key": 2}', '"x"', 'null'):
            with open(AUTH_FILE, "w") as f:
                f.write(raw)
            self.assertFalse(auth.configured(), raw)

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_fixing_permissions_is_noticed(self):
        self.set_up_env()
        self.assertTrue(auth.configured())
        os.chmod(AUTH_FILE, 0)
        auth._cache.update(stamp=None, creds={})   # as after a restart while the file is unreadable
        self.assertFalse(auth.configured())
        os.chmod(AUTH_FILE, 0o600)
        self.assertTrue(auth.configured())

    def test_short_key_refuses(self):
        self.set_up_env(key="k" * 31)
        self.assertFalse(auth.configured())

    def test_replaced_file_of_same_size_is_seen(self):
        other = "o" * len(KEY)
        self.set_up_env()
        self.assertTrue(auth.session_ok(f"nas_admin={auth.make_token(KEY, 1000)}", 0))
        auth.save(auth.hash_password("pw"), other)
        self.assertFalse(auth.session_ok(f"nas_admin={auth.make_token(KEY, 1000)}", 0))
        self.assertTrue(auth.session_ok(f"nas_admin={auth.make_token(other, 1000)}", 0))

    def test_change_password(self):
        self.set_up_env()
        old = f"nas_admin={auth.make_token(KEY, 1000)}"
        self.assertFalse(auth.change_password("wrong", "newpassword"))
        self.assertFalse(auth.change_password("pw", "short"))
        self.assertTrue(auth.session_ok(old, 0))
        self.assertTrue(auth.change_password("pw", "newpassword"))
        self.assertTrue(auth.login_ok("newpassword"))
        self.assertFalse(auth.login_ok("pw"))
        self.assertFalse(auth.session_ok(old, 0))

    def test_log_out_everywhere_keeps_password_changes_key(self):
        self.set_up_env()
        old = f"nas_admin={auth.make_token(KEY, 1000)}"
        auth.log_out_everywhere()
        self.assertTrue(auth.login_ok("pw"))
        self.assertTrue(auth.configured())
        self.assertFalse(auth.session_ok(old, 0))

    def test_saved_file_is_mode_600(self):
        auth.save(auth.hash_password("pw"), KEY)
        self.assertEqual(stat.S_IMODE(os.stat(AUTH_FILE).st_mode), 0o600)

    def test_was_remembered(self):
        self.set_up_env()
        long = auth.login_cookie(True, 1000).split(";")[0]
        short = auth.login_cookie(False, 1000).split(";")[0]
        self.assertTrue(auth.was_remembered(long, 1000))
        self.assertFalse(auth.was_remembered(short, 1000))
        self.assertFalse(auth.was_remembered(None, 1000))

    def test_session_ok_reads_the_cookie_among_others(self):
        self.set_up_env()
        tok = auth.make_token(KEY, 1000)
        self.assertTrue(auth.session_ok(f"a=b; nas_admin={tok}; c=d", 999))

    def test_session_refused_when_missing_or_garbled(self):
        self.set_up_env()
        for header in (None, "", "other=1", "nas_admin=", "nas_admin=abc", "=;;=", 'nas_admin="'):
            self.assertFalse(auth.session_ok(header, 0), header)

    def test_fails_closed_with_no_or_short_key(self):
        tok = auth.make_token("", 1000)
        self.assertFalse(auth.session_ok(f"nas_admin={tok}", 0))
        self.set_up_env(key="short")
        tok = auth.make_token("short", 1000)
        self.assertFalse(auth.session_ok(f"nas_admin={tok}", 0))
        self.assertFalse(auth.configured())

    def test_fails_closed_with_invalid_hash(self):
        self.write("nonsense", KEY)
        self.assertFalse(auth.configured())

    def test_configured(self):
        self.assertFalse(auth.configured())
        self.set_up_env()
        self.assertTrue(auth.configured())

    def test_startup_check_says_why_without_the_values(self):
        lines = []
        self.write("nonsense", "short-value")
        self.assertFalse(auth.startup_check(lines.append))
        self.assertEqual(len(lines), 1)
        self.assertIn(AUTH_FILE, lines[0])
        self.assertNotIn("short-value", lines[0])

    def test_startup_check_is_quiet_when_all_is_well(self):
        self.set_up_env()
        lines = []
        self.assertTrue(auth.startup_check(lines.append))
        self.assertEqual(lines, [])

    def test_login_cookie_flags(self):
        self.set_up_env()
        remembered = auth.login_cookie(True, 1000)
        for part in ("nas_admin=", "HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=2592000"):
            self.assertIn(part, remembered)
        self.assertNotIn("Domain", remembered)
        self.assertNotIn("Secure", remembered)
        tok = remembered.split(";")[0].split("=", 1)[1]
        self.assertTrue(auth.check_token(KEY, tok, 1000 + 30 * 86400 - 1))
        self.assertFalse(auth.check_token(KEY, tok, 1000 + 30 * 86400))

    def test_session_cookie_lasts_twelve_hours_with_no_max_age(self):
        self.set_up_env()
        cookie = auth.login_cookie(False, 1000)
        self.assertNotIn("Max-Age", cookie)
        tok = cookie.split(";")[0].split("=", 1)[1]
        self.assertTrue(auth.check_token(KEY, tok, 1000 + 12 * 3600 - 1))
        self.assertFalse(auth.check_token(KEY, tok, 1000 + 12 * 3600))

    def test_logout_cookie_expires_it(self):
        cookie = auth.logout_cookie()
        self.assertIn("nas_admin=;", cookie)
        self.assertIn("Max-Age=0", cookie)


class SafeNext(unittest.TestCase):
    def test_accepts_our_three_ports_on_the_same_host(self):
        for port in (3001, 8800, 8790):
            url = f"http://{HOST}:{port}/some/path?x=1#y"
            self.assertEqual(auth.safe_next(url, HOST), url)

    def test_rejects_everything_else(self):
        for bad in (None, "", "http://evil.example/", "//evil.example", f"http://{HOST}:5001/",
                    f"http://{HOST}@evil.example:8800/", f"http://evil.example:8800/", "javascript:alert(1)",
                    f"https://{HOST}:8800/", f"http://{HOST}/", f"http://{HOST}:notaport/", "/\\evil.example"):
            self.assertEqual(auth.safe_next(bad, HOST), "/admin/", bad)


class Throttling(unittest.TestCase):
    def test_no_wait_for_four_failures(self):
        t = auth.Throttle()
        for _ in range(4):
            t.fail("a", 100)
        self.assertEqual(t.wait("a", 100), 0)

    def test_doubles_from_the_fifth_failure_and_caps(self):
        t = auth.Throttle()
        for _ in range(5):
            t.fail("a", 100)
        self.assertEqual(t.wait("a", 100), 30)
        t.fail("a", 100)
        self.assertEqual(t.wait("a", 100), 60)
        for _ in range(20):
            t.fail("a", 100)
        self.assertEqual(t.wait("a", 100), 900)

    def test_wait_counts_down_and_addresses_are_separate(self):
        t = auth.Throttle()
        for _ in range(5):
            t.fail("a", 100)
        self.assertEqual(t.wait("a", 120), 10)
        self.assertEqual(t.wait("a", 130), 0)
        self.assertEqual(t.wait("b", 100), 0)

    def test_reset_clears(self):
        t = auth.Throttle()
        for _ in range(5):
            t.fail("a", 100)
        t.reset("a")
        self.assertEqual(t.wait("a", 100), 0)


class Fake:
    """Just enough of a request handler: records what auth sends."""
    def __init__(self, addr, headers, path="/", command="GET", port=3443):
        self.client_address = (addr, 5555)
        self.headers = headers
        self.path = path
        self.command = command
        self.server = type("S", (), {"server_address": ("0.0.0.0", port)})()
        self.code = None
        self.sent = {}
        self.wfile = io.BytesIO()
        self.close_connection = False

    def send_response(self, code):
        self.code = code

    def send_header(self, name, value):
        self.sent[name] = value

    def end_headers(self):
        pass


def fake(addr, headers, **kw):
    return Fake(addr, headers, **kw)


TS = "nas.example.ts.net"


class Https(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("NAS_TS_NAME", "HTTPS_PORT", "ADMIN_AUTH_FILE")}
        os.environ["NAS_TS_NAME"] = TS
        os.environ["HTTPS_PORT"] = "3443"
        os.environ["ADMIN_AUTH_FILE"] = AUTH_FILE
        with open(AUTH_FILE, "w") as f:
            json.dump({"hash": auth.hash_password("pw"), "key": KEY}, f)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        if os.path.exists(AUTH_FILE):
            os.remove(AUTH_FILE)

    def test_name_is_read_on_every_call_and_normalised(self):
        os.environ["NAS_TS_NAME"] = "  NAS.Example.TS.net "
        self.assertEqual(auth.ts_name(), TS)
        self.assertTrue(auth.https_on())
        os.environ["NAS_TS_NAME"] = ""
        self.assertFalse(auth.https_on())

    def test_https_url(self):
        self.assertEqual(auth.https_url(8843, "/x?y=1"), f"https://{TS}:8843/x?y=1")

    def test_via_proxy_needs_loopback_and_the_header(self):
        self.assertTrue(auth.via_proxy(fake("127.0.0.1", {"X-Forwarded-Proto": "https"})))
        self.assertFalse(auth.via_proxy(fake("192.168.1.20", {"X-Forwarded-Proto": "https"})))   # spoofed from the LAN
        self.assertFalse(auth.via_proxy(fake("127.0.0.1", {})))

    def test_internal_is_loopback_without_forwarding_headers(self):
        self.assertTrue(auth.internal(fake("127.0.0.1", {})))
        self.assertFalse(auth.internal(fake("127.0.0.1", {"X-Forwarded-For": "192.168.1.20"})))
        self.assertFalse(auth.internal(fake("127.0.0.1", {"X-Forwarded-Proto": "https"})))
        self.assertFalse(auth.internal(fake("192.168.1.20", {})))

    def test_gate_redirects_pages_keeping_the_query(self):
        h = fake("192.168.1.20", {}, path="/admin/?x=1")
        self.assertTrue(auth.plain_http_gate(h, 3443))
        self.assertEqual(h.code, 301)
        self.assertEqual(h.sent["Location"], f"https://{TS}:3443/admin/?x=1")

    def test_gate_refuses_api_and_post(self):
        for path, method in (("/api/settings", "GET"), ("/api/login", "POST")):
            h = fake("192.168.1.20", {}, path=path, command=method)
            self.assertTrue(auth.plain_http_gate(h, 3443))
            self.assertEqual(h.code, 403)
            self.assertTrue(h.close_connection)
            body = json.loads(h.wfile.getvalue())
            self.assertEqual(body, {"error": "use the HTTPS address", "url": f"https://{TS}:3443/"})

    def test_gate_lets_through_proxy_internal_and_exempt(self):
        self.assertFalse(auth.plain_http_gate(fake("127.0.0.1", {"X-Forwarded-Proto": "https"}), 3443))
        self.assertFalse(auth.plain_http_gate(fake("127.0.0.1", {}), 3443))
        self.assertFalse(auth.plain_http_gate(fake("192.168.1.20", {}, path="/tv"), 3443, lambda p: p == "/tv"))

    def test_exempt_sees_the_full_path_with_query(self):
        seen = []
        auth.plain_http_gate(fake("192.168.1.20", {}, path="/e?topic=opened"), 3443, lambda p: seen.append(p) or True)
        self.assertEqual(seen, ["/e?topic=opened"])

    def test_gate_is_off_without_a_name(self):
        os.environ["NAS_TS_NAME"] = ""
        self.assertFalse(auth.plain_http_gate(fake("192.168.1.20", {}, path="/admin/"), 3443))

    def test_cookies_are_secure_only_with_a_name(self):
        self.assertIn("; Secure", auth.login_cookie(True, 1000))
        self.assertIn("; Secure", auth.login_cookie(False, 1000))
        self.assertIn("; Secure", auth.logout_cookie())
        os.environ["NAS_TS_NAME"] = ""
        self.assertNotIn("Secure", auth.login_cookie(True, 1000))
        self.assertNotIn("Secure", auth.logout_cookie())

    def test_login_redirect_goes_to_the_https_login(self):
        os.environ["HTTPS_PORT"] = "8843"
        h = fake("192.168.1.20", {"Host": f"{TS}:8843"}, path="/x?a=1", port=8843)
        self.assertFalse(auth.require_login(h))
        self.assertEqual(h.code, 302)
        want = urllib.parse.quote(f"https://{TS}:8843/x?a=1", safe="")
        self.assertEqual(h.sent["Location"], f"https://{TS}:3443/?login=1&next={want}")


class SafeNextHttps(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("NAS_TS_NAME")
        os.environ["NAS_TS_NAME"] = TS

    def tearDown(self):
        os.environ.pop("NAS_TS_NAME", None)
        if self.saved is not None:
            os.environ["NAS_TS_NAME"] = self.saved

    def test_accepts_our_https_ports(self):
        for port in (3443, 8843, 8793):
            url = f"https://{TS}:{port}/x"
            self.assertEqual(auth.safe_next(url, TS), url)

    def test_rejects_http_other_hosts_and_ports(self):
        for url in (f"http://{TS}:3001/", "https://evil.example:3443/", f"https://{TS}:9443/"):
            self.assertEqual(auth.safe_next(url, TS), auth.DEFAULT_NEXT)


class Copies(unittest.TestCase):
    def test_every_stack_has_the_same_file(self):
        stacks = os.path.dirname(HERE)
        with open(os.path.join(HERE, "auth.py"), "rb") as f:
            ours = f.read()
        for other in ("mission-control/web/auth.py", "netwatch/auth.py"):
            with open(os.path.join(stacks, other), "rb") as f:
                self.assertEqual(f.read(), ours, other)


class Hostname(unittest.TestCase):
    def test_strips_the_port(self):
        class H:
            headers = {"Host": f"{HOST}:8800"}
        self.assertEqual(auth.request_hostname(H), HOST)


if __name__ == "__main__":
    unittest.main()
