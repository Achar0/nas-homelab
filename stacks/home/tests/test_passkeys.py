import base64
import hashlib
import json
import os
import stat
import struct
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import auth  # noqa: E402
import passkeys  # noqa: E402

TS = "nas.example.ts.net"
ORIGIN = f"https://{TS}:3443"


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def cbor(value):
    """Tiny CBOR encoder for the test data: ints, bytes, text, lists, dicts, bools, None."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for ai, fmt in ((24, ">B"), (25, ">H"), (26, ">I"), (27, ">Q")):
            if n < 1 << (8 * struct.calcsize(fmt)):
                return bytes([major << 5 | ai]) + struct.pack(fmt, n)
        raise ValueError(n)
    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(value)


class Authenticator:
    """A software passkey that builds real WebAuthn data, for tests (Home's HTTP tests use it too).

    Authenticator(rp_id, origin, alg=-7): a new credential with a P-256 (-7) or RSA-2048 (-257) key.
    .cred_id is its id (base64url), .raw_id the same as bytes.
    register(challenge, spoil=None) -> (client_data_json, attestation_object)
    login(challenge, spoil=None, sign_count=0) -> (cred_id, client_data_json, authenticator_data, signature)
    spoil names one thing to get wrong (see the tests below); sign_count goes into the authenticator data.
    """
    UP, UV, AT, ED = 0x01, 0x04, 0x40, 0x80

    def __init__(self, rp_id, origin, alg=-7):
        self.rp_id, self.origin, self.alg = rp_id, origin, alg
        self.raw_id = os.urandom(32)
        self.cred_id = b64url(self.raw_id)
        if alg == -7:
            self.key = ec.generate_private_key(ec.SECP256R1())
        elif alg == -257:
            self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        else:
            raise ValueError(alg)

    def cose_key(self):
        nums = self.key.public_key().public_numbers()
        if self.alg == -7:
            return {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        return {1: 3, 3: -257, -1: nums.n.to_bytes(256, "big"), -2: nums.e.to_bytes(3, "big")}

    def client_data(self, kind, challenge, spoil):
        origin = {"http_origin": f"http://{TS}:3443", "wrong_port_origin": f"https://{TS}:3001"}.get(spoil, self.origin)
        data = {"type": "webauthn.get" if spoil == "wrong_type" and kind == "webauthn.create"
                else "webauthn.create" if spoil == "wrong_type" else kind,
                "challenge": "A" * 43 if spoil == "bad_challenge" else challenge,
                "origin": origin, "crossOrigin": spoil == "cross_origin"}
        return json.dumps(data).encode()

    def auth_data(self, spoil, sign_count, attested):
        rp_id = "100.64.0.1" if spoil == "ip_rp_id" else self.rp_id
        flags = self.UP | self.UV
        if spoil == "no_uv":
            flags &= ~self.UV
        if spoil == "no_up":
            flags &= ~self.UP
        tail = b""
        if attested:
            flags |= self.AT
            key = self.cose_key()
            if spoil == "ed25519_key":
                raw = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                key = {1: 1, 3: -8, -1: 6, -2: raw}
            tail = bytes(16) + struct.pack(">H", len(self.raw_id)) + self.raw_id + cbor(key)
        return hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", sign_count) + tail

    def sign(self, data):
        if self.alg == -7:
            return self.key.sign(data, ec.ECDSA(hashes.SHA256()))
        return self.key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    def register(self, challenge, spoil=None):
        cdj = self.client_data("webauthn.create", challenge, spoil)
        auth_data = self.auth_data(spoil, 0, attested=spoil != "no_attested_data")
        return cdj, cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})

    def login(self, challenge, spoil=None, sign_count=0):
        cdj = self.client_data("webauthn.get", challenge, spoil)
        auth_data = self.auth_data(spoil, sign_count, attested=False)
        sig = self.sign(auth_data + hashlib.sha256(cdj).digest())
        if spoil == "bad_signature":   # signed by the right key, but over different data
            sig = self.sign(auth_data + hashlib.sha256(cdj + b" ").digest())
        return self.cred_id, cdj, auth_data, sig


class TsName(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("NAS_TS_NAME")
        os.environ["NAS_TS_NAME"] = TS

    def tearDown(self):
        os.environ.pop("NAS_TS_NAME", None)
        if self.saved is not None:
            os.environ["NAS_TS_NAME"] = self.saved


class Cbor(unittest.TestCase):
    def test_decodes_maps_bytes_text_ints(self):
        value = {1: 2, 3: -7, -1: 1, -300: b"\x00" * 40, "fmt": "none", "list": [0, 23, 24, 255, 256, 65536, 2 ** 40, -1, -25, -(2 ** 33)],
                 "nested": {"t": True, "f": False, "n": None}, "empty": []}
        self.assertEqual(passkeys.cbor_decode(cbor(value)), value)

    def test_refuses_indefinite_lengths_trailing_bytes_and_deep_nesting(self):
        deep = cbor([[[[[[[[[1]]]]]]]]])   # 9 levels
        ok = cbor([[[[[[[[1]]]]]]]])       # 8 levels
        self.assertEqual(passkeys.cbor_decode(ok), [[[[[[[[1]]]]]]]])
        bad = {
            "indefinite map": b"\xbf\x01\x02\xff",
            "indefinite bytes": b"\x5f\x41\x00\xff",
            "trailing": cbor(1) + b"\x00",
            "deep": deep,
            "tag": b"\xc0\x60",
            "float": b"\xf9\x00\x00",
            "undefined": b"\xf7",
            "truncated": b"\x44\x00\x01",
            "empty": b"",
            "huge array": b"\x9b" + b"\xff" * 8,
            "bad utf-8": b"\x61\xff",
            "duplicate key": b"\xa2\x01\x01\x01\x02",
            "list as key": b"\xa1\x80\x01",
            "reserved ai": b"\x1c",
        }
        for name, data in bad.items():
            with self.subTest(name), self.assertRaises(passkeys.PasskeyError):
                passkeys.cbor_decode(data)


class Options(TsName):
    def test_registration_options(self):
        o = passkeys.registration_options("ch", [{"id": "abc"}])
        self.assertEqual(o["rp"], {"id": TS, "name": "NAS"})
        self.assertEqual(o["user"], {"id": "YWRtaW4", "name": "admin", "displayName": "NAS admin"})
        self.assertEqual([p["alg"] for p in o["pubKeyCredParams"]], [-7, -257])
        self.assertEqual(o["authenticatorSelection"], {"residentKey": "required", "userVerification": "required"})
        self.assertEqual(o["attestation"], "none")
        self.assertEqual(o["excludeCredentials"], [{"type": "public-key", "id": "abc"}])
        self.assertEqual((o["challenge"], o["timeout"]), ("ch", 120000))

    def test_login_options(self):
        self.assertEqual(passkeys.login_options("ch"),
                         {"challenge": "ch", "rpId": TS, "userVerification": "required", "timeout": 120000,
                          "allowCredentials": []})


class Register(TsName):
    def setUp(self):
        super().setUp()
        self.challenge = passkeys.Challenges().new("register", 0)
        self.auth = Authenticator(TS, ORIGIN)

    def ok(self, c):
        return c == self.challenge

    def test_es256_and_rs256_are_accepted(self):
        for alg in (-7, -257):
            with self.subTest(alg):
                a = Authenticator(TS, ORIGIN, alg)
                entry = passkeys.verify_registration(*a.register(self.challenge), self.ok)
                self.assertEqual(entry["id"], a.cred_id)
                self.assertEqual((entry["alg"], entry["sign_count"]), (alg, 0))
                self.assertEqual(passkeys.cbor_decode(base64.urlsafe_b64decode(entry["public_key"] + "==")), a.cose_key())

    def test_rejections(self):
        for case in ("wrong_type", "bad_challenge", "http_origin", "wrong_port_origin", "ip_rp_id", "no_uv", "no_up",
                     "no_attested_data", "ed25519_key", "cross_origin"):
            with self.subTest(case), self.assertRaises(passkeys.PasskeyError):
                passkeys.verify_registration(*self.auth.register(self.challenge, spoil=case), self.ok)

    def test_garbage_is_a_passkey_error(self):
        cdj, att = self.auth.register(self.challenge)
        for bad_cdj, bad_att in ((b"not json", att), (b"[]", att), (cdj, b"\x00"), (cdj, cbor({"fmt": "none"})),
                                 (cdj, cbor({"fmt": "none", "attStmt": {}, "authData": b"short"}))):
            with self.subTest(bad_cdj=bad_cdj, bad_att=bad_att[:8]), self.assertRaises(passkeys.PasskeyError):
                passkeys.verify_registration(bad_cdj, bad_att, self.ok)

    def test_needs_ts_name(self):
        os.environ["NAS_TS_NAME"] = ""
        with self.assertRaises(passkeys.PasskeyError):
            passkeys.verify_registration(*Authenticator("", "https://:3443").register(self.challenge), self.ok)


class Login(TsName):
    def setUp(self):
        super().setUp()
        self.challenge = "c" * 43
        self.auth = Authenticator(TS, ORIGIN)
        self.stored = passkeys.verify_registration(*self.auth.register("r"), lambda c: True)

    def ok(self, c):
        return c == self.challenge

    def test_good_assertion_returns_the_new_count(self):
        self.stored["sign_count"] = 4
        self.assertEqual(passkeys.verify_login(*self.auth.login(self.challenge, sign_count=5), self.stored, self.ok), 5)

    def test_rs256(self):
        a = Authenticator(TS, ORIGIN, -257)
        stored = passkeys.verify_registration(*a.register("r"), lambda c: True)
        self.assertEqual(passkeys.verify_login(*a.login(self.challenge, sign_count=1), stored, self.ok), 1)

    def test_rejections(self):
        for case in ("bad_signature", "unknown_credential", "wrong_type", "bad_challenge", "http_origin",
                     "wrong_port_origin", "ip_rp_id", "no_uv", "no_up", "count_went_back", "count_stayed",
                     "count_reset_to_zero", "cross_origin"):
            stored = dict(self.stored, sign_count=7)
            count = {"count_went_back": 6, "count_stayed": 7, "count_reset_to_zero": 0}.get(case, 8)
            if case == "unknown_credential":
                stored = None
            with self.subTest(case), self.assertRaises(passkeys.PasskeyError):
                passkeys.verify_login(*self.auth.login(self.challenge, spoil=case, sign_count=count), stored, self.ok)

    def test_signature_from_another_key_is_refused(self):
        other = Authenticator(TS, ORIGIN)
        _, cdj, ad, sig = other.login(self.challenge)
        with self.assertRaises(passkeys.PasskeyError):
            passkeys.verify_login(self.auth.cred_id, cdj, ad, sig, self.stored, self.ok)

    def test_tampered_authenticator_data_is_refused(self):
        cred, cdj, ad, sig = self.auth.login(self.challenge, sign_count=3)
        tampered = ad[:33] + struct.pack(">I", 9)
        with self.assertRaises(passkeys.PasskeyError):
            passkeys.verify_login(cred, cdj, tampered, sig, self.stored, self.ok)

    def test_credential_id_must_match_the_stored_one(self):
        _, cdj, ad, sig = self.auth.login(self.challenge)
        with self.assertRaises(passkeys.PasskeyError):
            passkeys.verify_login("other", cdj, ad, sig, self.stored, self.ok)

    def test_garbage_signature_is_a_passkey_error(self):
        cred, cdj, ad, _ = self.auth.login(self.challenge)
        for sig in (b"", b"\x30\x00", b"\x00" * 70):
            with self.subTest(sig), self.assertRaises(passkeys.PasskeyError):
                passkeys.verify_login(cred, cdj, ad, sig, self.stored, self.ok)

    def test_apple_style_zero_counter_is_accepted_twice(self):
        for _ in range(2):
            self.assertEqual(passkeys.verify_login(*self.auth.login(self.challenge), self.stored, self.ok), 0)


class ChallengeTests(unittest.TestCase):
    def test_single_use(self):
        ch = passkeys.Challenges()
        c = ch.new("login", 0)
        self.assertEqual(len(base64.urlsafe_b64decode(c + "=")), 32)
        self.assertTrue(ch.take("login", c, 1))
        self.assertFalse(ch.take("login", c, 2))

    def test_expires_after_120_s(self):
        ch = passkeys.Challenges()
        c = ch.new("login", 1000)
        self.assertFalse(ch.take("login", c, 1121))
        c = ch.new("login", 1000)
        self.assertTrue(ch.take("login", c, 1119))

    def test_kind_must_match(self):
        ch = passkeys.Challenges()
        c = ch.new("register", 0)
        self.assertFalse(ch.take("login", c, 1))
        self.assertFalse(ch.take("register", c, 1))   # a failed take still uses it up

    def test_keeps_at_most_100(self):
        ch = passkeys.Challenges()
        first = ch.new("login", 0)
        rest = [ch.new("login", i / 1000) for i in range(1, 101)]
        self.assertFalse(ch.take("login", first, 1))
        self.assertTrue(ch.take("login", rest[0], 1))
        self.assertTrue(ch.take("login", rest[-1], 1))

    def test_unknown_or_odd_values_are_refused(self):
        ch = passkeys.Challenges()
        ch.new("login", 0)
        for bad in ("", "nope", "é" * 43, None, 5):
            self.assertFalse(ch.take("login", bad, 1), bad)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "passkeys.json")
        self.store = passkeys.Store(self.path)

    def entry(self, i=0):
        return {"id": f"id{i}", "public_key": "pk", "alg": -7, "sign_count": 0}

    def test_add_list_touch_remove_and_mode_600(self):
        self.store.add(self.entry(), "  iPhone  ", 100)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual([p["name"] for p in self.store.all()], ["iPhone"])
        self.assertEqual(self.store.get("id0")["created"], 100)
        self.assertIsNone(self.store.get("nope"))
        self.store.touch("id0", 5, 200)
        again = passkeys.Store(self.path).get("id0")
        self.assertEqual((again["sign_count"], again["last_used"]), (5, 200))
        with open(self.path) as f:
            self.assertEqual(list(json.load(f)), ["passkeys"])
        self.assertTrue(self.store.remove("id0"))
        self.assertFalse(self.store.remove("id0"))
        self.assertEqual(self.store.all(), [])
        self.assertEqual(os.listdir(self.dir), ["passkeys.json"])   # no temp files left

    def test_same_credential_twice_is_refused(self):
        self.store.add(self.entry(), "a", 0)
        with self.assertRaises(passkeys.PasskeyError):
            self.store.add(self.entry(), "b", 0)

    def test_missing_or_broken_file_is_empty(self):
        self.assertEqual(self.store.all(), [])
        for content in ("", "not json", "[]", '{"passkeys": 5}', '{"other": []}'):
            with open(self.path, "w") as f:
                f.write(content)
            self.assertEqual(self.store.all(), [], content)
        self.store.add(self.entry(), "a", 0)
        self.assertEqual(len(self.store.all()), 1)

    def test_name_rules_and_limit_of_20(self):
        for bad in ("", "   ", "x" * 41, "a\nb", None):
            with self.subTest(bad), self.assertRaises(passkeys.PasskeyError):
                self.store.add(self.entry(), bad, 0)
        self.store.add(self.entry(0), "x" * 40, 0)
        for i in range(1, 20):
            self.store.add(self.entry(i), f"key {i}", 0)
        with self.assertRaises(passkeys.PasskeyError):
            self.store.add(self.entry(20), "one too many", 0)
        self.assertEqual(len(self.store.all()), 20)

    def test_default_path_is_next_to_auth_json(self):
        saved = os.environ.get("ADMIN_AUTH_FILE")
        os.environ["ADMIN_AUTH_FILE"] = os.path.join(self.dir, "auth.json")
        try:
            self.assertEqual(passkeys.default_path(), os.path.join(self.dir, "passkeys.json"))
        finally:
            os.environ.pop("ADMIN_AUTH_FILE")
            if saved is not None:
                os.environ["ADMIN_AUTH_FILE"] = saved

    def test_auth_save_does_not_touch_passkeys(self):
        saved = os.environ.get("ADMIN_AUTH_FILE")
        os.environ["ADMIN_AUTH_FILE"] = os.path.join(self.dir, "auth.json")
        try:
            auth.save(auth.hash_password("correct horse"), "k" * 64)
            store = passkeys.Store(passkeys.default_path())
            store.add(self.entry(), "iPhone", 0)
            with open(passkeys.default_path(), "rb") as f:
                before = f.read()
            auth.log_out_everywhere()
            with open(passkeys.default_path(), "rb") as f:
                self.assertEqual(f.read(), before)
        finally:
            os.environ.pop("ADMIN_AUTH_FILE")
            if saved is not None:
                os.environ["ADMIN_AUTH_FILE"] = saved


if __name__ == "__main__":
    unittest.main()
