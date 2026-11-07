import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import auth  # noqa: E402

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
        self.saved = {k: os.environ.pop(k, None) for k in ("SESSION_SECRET", "ADMIN_PASSWORD_HASH")}

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def set_up_env(self, key=KEY):
        os.environ["SESSION_SECRET"] = key
        os.environ["ADMIN_PASSWORD_HASH"] = auth.hash_password("pw")

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
        self.set_up_env()
        os.environ["ADMIN_PASSWORD_HASH"] = "nonsense"
        self.assertFalse(auth.configured())

    def test_configured(self):
        self.assertFalse(auth.configured())
        self.set_up_env()
        self.assertTrue(auth.configured())

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
