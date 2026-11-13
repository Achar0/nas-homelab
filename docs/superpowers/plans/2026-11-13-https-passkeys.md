# HTTPS and Passkey Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Home, Mission Control and Netwatch over HTTPS on the NAS's Tailscale name through Caddy, redirect the old HTTP addresses, and add passkey sign-in to Home.

**Architecture:** Caddy (new stack, host network) gets the `*.ts.net` certificate from the tailscaled socket and proxies three HTTPS ports to the unchanged HTTP servers on loopback. The shared `auth.py` learns to tell "came through Caddy" from "internal loopback call" from "plain HTTP from the network", and redirects or refuses the last one. Passkeys live in a new Home-only module `passkeys.py`, which verifies WebAuthn with `cryptography`.

**Tech Stack:** Python 3.12 stdlib servers, `cryptography` (Home only), Caddy 2, vanilla JS, Docker Compose on UGOS.

**Spec:** `docs/superpowers/specs/2026-11-13-https-passkeys-design.md`

## Global Constraints

- The repo is public. Never commit the tailnet name, the Tailscale IP or a `.env`. Docs and tests use `nas.example.ts.net`, or `<nas-name>.<tailnet>.ts.net` in prose.
- HTTPS ports: Home `3443`, Mission Control `8843`, Netwatch `8793`. HTTP ports stay `3001`, `8800`, `8790`.
- Env names: `NAS_TS_NAME` (full MagicDNS name) and `HTTPS_PORT` (this service's HTTPS port). An unset or empty `NAS_TS_NAME` means today's HTTP behaviour: no redirects, no `Secure` flag, no passkeys.
- `auth.py` stays standard-library only and byte-identical in `stacks/home`, `stacks/mission-control/web` and `stacks/netwatch` (`tests/test_auth.py::Copies`).
- Only Home depends on `cryptography`, pinned to an exact version (the newest release at least two weeks old, checked on PyPI). Caddy image: `caddy:2.10.0`, or a newer 2.10.x at least two weeks old.
- Plain-HTTP exceptions on Home: `/tv`, anything under `/tv/`, `/api/public/tv`, `/api/news` (the public view), `/iptv.m3u`.
- Passkeys: RP ID = `NAS_TS_NAME`; origin = `https://{NAS_TS_NAME}:3443`; `residentKey: "required"`, `userVerification: "required"`, `attestation: "none"`, algorithms ES256 (-7) and RS256 (-257); challenges are single use, expire after 120 s and are kept in memory.
- Commit as `Achar0 <98092805+Achar0@users.noreply.github.com>`, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test commands: plain `python -m unittest` works for Mission Control and Netwatch. Home needs `cryptography`, so create a venv once and use it:
  `python -m venv ~/.cache/nas-homelab-venv && ~/.cache/nas-homelab-venv/bin/pip install cryptography==<pinned>`, then `cd stacks/home && ~/.cache/nas-homelab-venv/bin/python -m unittest discover -s tests -t .`
- UI copy is English, calm HIG style, no nested boxes (CLAUDE.md).

## Review Focus

1. **A request through Caddy reaches a loopback-only door.** Netwatch's `LOOPBACK` exemption and Home's `/api/internal/layout` must refuse a loopback request that carries `X-Forwarded-Proto` or `X-Forwarded-For`. Tests: Task 2.
2. **A spoofed header from the network.** A LAN client sending `X-Forwarded-Proto: https` straight to `:3001` must still get the plain-HTTP treatment (redirect or 403). Tests: Task 1 (`via_proxy`) and Task 2 (route).
3. **The TV and IPTV players keep working over HTTP**, including `/tv?demo=…` query strings and `/api/news?topic=all`. Meanwhile `/api/news?topic=opened` over HTTP is redirected, never served. Test: Task 2.
4. **A missing `NAS_TS_NAME` locks nobody out.** The services behave exactly as before, and the passkey endpoints answer 404. Tests: Task 1, Task 4.
5. **A passkey assertion replayed or reused across origins:** the same challenge twice, a challenge from another session, `http://` origin, origin with the wrong port, an RP ID hash for `192.168.1.14`. Tests: Task 3.

---

### Task 1: Shared `auth.py` learns about HTTPS

**Files:**
- Modify: `stacks/home/auth.py`, then copy it byte-for-byte to `stacks/mission-control/web/auth.py` and `stacks/netwatch/auth.py`
- Test: `stacks/home/tests/test_auth.py`

**Interfaces:**
- Produces:
  - `ts_name() -> str`: `os.environ.get("NAS_TS_NAME", "").strip().lower()`, read on every call.
  - `https_on() -> bool`: `bool(ts_name())`.
  - `via_proxy(handler) -> bool`: loopback `client_address[0]` **and** header `X-Forwarded-Proto == "https"`.
  - `internal(handler) -> bool`: loopback **and** neither `X-Forwarded-Proto` nor `X-Forwarded-For` is present.
  - `https_url(port: int, path: str) -> str`: `f"https://{ts_name()}:{port}{path}"`.
  - `plain_http_gate(handler, https_port: int, exempt=lambda path: False) -> bool`: True if it answered the request. It does nothing (False) when `https_on()` is False, the request is `via_proxy` or `internal`, or `exempt(path)` holds. Otherwise: GET/HEAD to a non-`/api/` path → `301` to `https_url(https_port, handler.path)`, keeping the query. Anything else → `403` JSON `{"error": "use the HTTPS address", "url": https_url(https_port, "/")}`, with `close_connection = True` so no body is read.
  - `LOOPBACK = {"127.0.0.1", "::1"}`, moved here from the servers.
  - `HTTPS_LOGIN_PORT = 3443`, `HTTPS_NEXT_PORTS = (3443, 8843, 8793)`.
- Changed behaviour, only when `https_on()`:
  - `login_cookie` and `logout_cookie` append `; Secure`.
  - `require_login` redirects to `https://{ts_name()}:3443/?login=1&next=<quoted https://{ts_name()}:{HTTPS_PORT env}{path}>`.
  - `safe_next` accepts only `https` URLs whose hostname is `ts_name()` and whose port is in `HTTPS_NEXT_PORTS`.

  With `https_on()` False, all three behave exactly as today.

- [ ] **Step 1: Write the failing tests** (new classes in `test_auth.py`, using a fake handler with `client_address`, `headers`, `path`, `command`, and a recording `send_response`/`send_header`/`end_headers`/`wfile`)

```python
class Https(unittest.TestCase):          # setUp sets NAS_TS_NAME="nas.example.ts.net", HTTPS_PORT="3443"; tearDown clears both
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
        self.assertEqual(h.sent["Location"], "https://nas.example.ts.net:3443/admin/?x=1")
    def test_gate_refuses_api_and_post(self):
        for path, method in (("/api/settings", "GET"), ("/api/login", "POST")):
            h = fake("192.168.1.20", {}, path=path, command=method)
            self.assertTrue(auth.plain_http_gate(h, 3443)); self.assertEqual(h.code, 403)
    def test_gate_lets_through_proxy_internal_and_exempt(self):
        self.assertFalse(auth.plain_http_gate(fake("127.0.0.1", {"X-Forwarded-Proto": "https"}), 3443))
        self.assertFalse(auth.plain_http_gate(fake("127.0.0.1", {}), 3443))
        self.assertFalse(auth.plain_http_gate(fake("192.168.1.20", {}, path="/tv"), 3443, lambda p: p == "/tv"))
    def test_gate_is_off_without_a_name(self):          # clears NAS_TS_NAME first
        self.assertFalse(auth.plain_http_gate(fake("192.168.1.20", {}, path="/admin/"), 3443))
    def test_cookies_are_secure_only_with_a_name(self): ...   # "; Secure" in login_cookie/logout_cookie iff NAS_TS_NAME set
    def test_login_redirect_goes_to_the_https_login(self): ...  # require_login on a GET page → Location starts "https://nas.example.ts.net:3443/?login=1&next=https%3A%2F%2Fnas.example.ts.net%3A3443"

class SafeNextHttps(unittest.TestCase):
    def test_accepts_our_https_ports(self):
        for port in (3443, 8843, 8793):
            url = f"https://nas.example.ts.net:{port}/x"
            self.assertEqual(auth.safe_next(url, "nas.example.ts.net"), url)
    def test_rejects_http_other_hosts_and_ports(self):
        for url in ("http://nas.example.ts.net:3001/", "https://evil.example:3443/", "https://nas.example.ts.net:9443/"):
            self.assertEqual(auth.safe_next(url, "nas.example.ts.net"), auth.DEFAULT_NEXT)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd stacks/home && python -m unittest tests.test_auth -v`
Expected: the new tests ERROR with `AttributeError: module 'auth' has no attribute 'via_proxy'`. The existing tests still pass.

- [ ] **Step 3: Implement the interfaces above in `stacks/home/auth.py`**, update the module docstring (HTTPS mode, `NAS_TS_NAME`), then copy the file to the other two stacks.

- [ ] **Step 4: Run every auth suite**

Run: `cd stacks/home && python -m unittest tests.test_auth -v && cd ../netwatch && python -m unittest discover -s tests -t . && cd ../mission-control/web && python -m unittest discover -s tests -t .`
Expected: all OK, `Copies` included.

- [ ] **Step 5: Commit** — `auth: HTTPS mode with NAS_TS_NAME, plain-HTTP gate, Secure cookie (#6)`

---

### Task 2: Wire the gate into the three servers and close the loopback doors

**Files:**
- Modify: `stacks/home/server.py` (`LOOPBACK` line 59, `do_HEAD`, `do_GET`, `do_POST`, `/api/internal/layout`)
- Modify: `stacks/mission-control/web/server.py` (`do_HEAD`, `do_GET`)
- Modify: `stacks/netwatch/app.py` (`LOOPBACK` line 35, `allowed()` line 362)
- Modify: `stacks/home/docker-compose.yaml`, `stacks/mission-control/docker-compose.yaml` (service `web`), `stacks/netwatch/docker-compose.yaml`: add `NAS_TS_NAME: ${NAS_TS_NAME:-}` and `HTTPS_PORT: "3443"` / `"8843"` / `"8793"` to `environment`. Add a `NAS_TS_NAME=` line to each stack's `.env.example` (create one for Home if missing).
- Test: `stacks/home/tests/test_routes.py`, `stacks/netwatch/tests/test_gate.py`, `stacks/mission-control/web/tests/test_server.py`

**Interfaces:**
- Consumes: `auth.plain_http_gate`, `auth.internal`, `auth.via_proxy`, `auth.LOOPBACK` (Task 1).
- Produces: `server.http_exempt(path: str) -> bool` in Home: true for `/tv`, `/tv/…`, `/api/public/tv`, `/iptv.m3u`, and `/api/news` unless the query contains `topic=opened`. Its signature takes the full `handler.path`, so it can see the query.

Each `do_HEAD` / `do_GET` / `do_POST` starts with `if auth.plain_http_gate(self, HTTPS_PORT, …): return`, where `HTTPS_PORT = int(os.environ.get("HTTPS_PORT", "0"))`. In Home this runs before `from_another_site`. Home's `/api/internal/layout` and Netwatch's `allowed()` use `auth.internal(self)` instead of the `LOOPBACK` set.

- [ ] **Step 1: Write the failing route tests.** In Home's `test_routes.py`, add a class with `NAS_TS_NAME=nas.example.ts.net` and `HTTPS_PORT=3443` set in `setUpClass` (and cleared in `tearDownClass`). Test clients are on 127.0.0.1, so "from the network" is simulated by patching `auth.LOOPBACK` to an empty set for those tests.

```python
def test_pages_redirect_to_https(self):            # LOOPBACK patched empty
    r = self.call("/admin/settings?tab=account")
    self.assertEqual((r.status, r.getheader("Location")), (301, "https://nas.example.ts.net:3443/admin/settings?tab=account"))
def test_login_over_http_is_refused(self):
    self.assertEqual(self.call("/api/login", "POST", body={"pw": PW}).status, 403)
def test_tv_and_playlist_stay_on_http(self):
    for path in ("/tv", "/tv/tv.js", "/tv?demo=urgent", "/api/public/tv", "/api/news?topic=all"):
        self.assertNotIn(self.call(path).status, (301, 403), path)
def test_opened_news_is_not_an_exception(self):
    self.assertEqual(self.call("/api/news?topic=opened").status, 403)
def test_spoofed_proxy_header_from_the_network_is_still_redirected(self):
    self.assertEqual(self.call("/admin/", headers={"X-Forwarded-Proto": "https"}).status, 301)
def test_internal_layout_refuses_requests_through_caddy(self):   # real loopback
    self.assertEqual(self.call("/api/internal/layout", headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "192.168.1.20"}).status, 401)
    self.assertEqual(self.call("/api/internal/layout").status, 200)
def test_without_a_name_nothing_changes(self): ...   # NAS_TS_NAME cleared → /admin/ gives the usual login redirect, not 301
```

  `call()` gains a `headers=None` argument. In Netwatch's `test_gate.py`: a loopback request with `X-Forwarded-Proto: https` and no cookie gets 401 (or the login redirect for a page); a loopback request without the header still gets 200. In Mission Control's `test_server.py`: `/` from the network with `NAS_TS_NAME` set gets 301 to `https://nas.example.ts.net:8843/`.

- [ ] **Step 2: Run them to verify they fail**

Run: the three suites as in Task 1, Step 4.
Expected: the new tests FAIL (200 or 302 where 301/403/401 is expected).

- [ ] **Step 3: Implement the wiring above**, plus the compose and `.env.example` changes.

- [ ] **Step 4: Run all three suites.** Expected: all OK.

- [ ] **Step 5: Commit** — `Home, Mission Control, Netwatch: redirect plain HTTP, trust only internal loopback (#6)`

---

### Task 3: `passkeys.py`, WebAuthn verification and storage (Home)

**Files:**
- Create: `stacks/home/passkeys.py`
- Create: `stacks/home/tests/test_passkeys.py`
- Modify: `stacks/home/Dockerfile`: `RUN pip install --no-cache-dir cryptography==<pinned>` before `COPY`; add `passkeys.py` to the `COPY` line; the comment becomes "Standard library plus cryptography (passkey signatures)".

**Interfaces:**
- Consumes: `auth.ts_name()`, `auth.HTTPS_LOGIN_PORT` (Task 1).
- Produces:
  - `class PasskeyError(ValueError)`: the message is a short reason for logs, never shown with secrets.
  - `cbor_decode(data: bytes) -> object`: major types 0–5 and 7 (false, true, null), definite lengths only. Raises `PasskeyError` on anything else, on trailing bytes, or on nesting deeper than 8.
  - `class Challenges`: `new(kind: str, now: float) -> str` (base64url of 32 random bytes) and `take(kind: str, challenge: str, now: float) -> bool`. `take` removes the challenge, accepts it only if it has the same kind and is under 120 s old, and keeps at most 100 pending challenges, dropping the oldest. Thread-safe. `kind` is `"register"` or `"login"`.
  - `registration_options(challenge: str, existing: list[dict]) -> dict`: the `publicKey` options JSON, with `rp {id, name: "NAS"}`, `user {id: base64url(b"admin"), name: "admin", displayName: "NAS admin"}`, `pubKeyCredParams` with -7 and -257, `authenticatorSelection {residentKey: "required", userVerification: "required"}`, `attestation: "none"`, `excludeCredentials` from `existing`, and `timeout: 120000`.
  - `login_options(challenge: str) -> dict`: `{challenge, rpId, userVerification: "required", timeout: 120000}` (empty `allowCredentials`).
  - `verify_registration(client_data_json: bytes, attestation_object: bytes, challenge_ok: Callable[[str], bool]) -> dict`. It returns `{"id": b64url, "public_key": b64url(COSE bytes), "alg": int, "sign_count": int}` after checking:
    - `type == "webauthn.create"`, the challenge via `challenge_ok`, and `origin == https://{ts_name}:3443`;
    - the RP ID hash = `sha256(ts_name)` and the UP and UV flags;
    - that attested credential data is present and the COSE key is EC2 P-256 (-7) or RSA (-257).
  - `verify_login(cred_id: str, client_data_json: bytes, authenticator_data: bytes, signature: bytes, stored: dict | None, challenge_ok) -> int`. It returns the new sign count after checking `type == "webauthn.get"`, the challenge, the origin, the RP ID hash, UP + UV, and `stored is not None`. It verifies `signature` over `authenticator_data + sha256(client_data_json)`: ECDSA-SHA256 (DER) for -7, PKCS1v15-SHA256 for -257. If both counts are non-zero, the new one must be greater than the stored one.
  - `class Store(path: str)`: `all() -> list[dict]`, `get(cred_id) -> dict | None`, `add(entry: dict, name: str, now: float)` (name is stripped, 1–40 chars, otherwise `PasskeyError`; at most 20 passkeys), `remove(cred_id) -> bool`, `touch(cred_id, sign_count, now)`. It writes `{"passkeys": [...]}` atomically with mode 600 (mkstemp + `os.replace`, as in `auth.save`) and treats a missing or invalid file as empty. Default path: `os.path.join(os.path.dirname(auth.auth_file()), "passkeys.json")`.

- [ ] **Step 1: Write the failing tests.** A test helper `Authenticator` (in the test file) builds real WebAuthn data with `cryptography`: it generates a P-256 key (and an RSA-2048 key for one test), encodes the COSE key and the attestation object with a tiny CBOR *encoder* in the test, builds authenticator data (`rp_id_hash || flags || counter || attested data`), and signs `authData + sha256(clientDataJSON)`.

```python
class Cbor(unittest.TestCase):
    def test_decodes_maps_bytes_text_ints(self): ...       # round-trips the test encoder's output, negative ints included
    def test_refuses_indefinite_lengths_trailing_bytes_and_deep_nesting(self): ...   # each → PasskeyError

class Register(unittest.TestCase):     # NAS_TS_NAME=nas.example.ts.net
    def test_es256_and_rs256_are_accepted(self): ...       # returns id, alg -7 / -257, sign_count
    def test_rejections(self):
        for case in ("wrong_type", "bad_challenge", "http_origin", "wrong_port_origin", "ip_rp_id", "no_uv", "no_up", "no_attested_data", "ed25519_key"):
            with self.subTest(case), self.assertRaises(passkeys.PasskeyError):
                passkeys.verify_registration(*self.auth.register(spoil=case), lambda c: c == self.challenge)

class Login(unittest.TestCase):
    def test_good_assertion_returns_the_new_count(self): ...
    def test_rejections(self):
        for case in ("bad_signature", "unknown_credential", "wrong_type", "http_origin", "wrong_port_origin", "ip_rp_id", "no_uv", "count_went_back"):
            ...  # each → PasskeyError
    def test_apple_style_zero_counter_is_accepted_twice(self): ...

class ChallengeTests(unittest.TestCase):
    def test_single_use(self): c = ch.new("login", 0); self.assertTrue(ch.take("login", c, 1)); self.assertFalse(ch.take("login", c, 2))
    def test_expires_after_120_s(self): ...    # take at now+121 → False
    def test_kind_must_match(self): ...        # a "register" challenge can't be used for "login"
    def test_keeps_at_most_100(self): ...      # 101st new() evicts the first

class StoreTests(unittest.TestCase):
    def test_add_list_touch_remove_and_mode_600(self): ...
    def test_missing_or_broken_file_is_empty(self): ...
    def test_name_rules_and_limit_of_20(self): ...
    def test_auth_save_does_not_touch_passkeys(self): ...   # auth.log_out_everywhere() leaves passkeys.json identical
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd stacks/home && ~/.cache/nas-homelab-venv/bin/python -m unittest tests.test_passkeys -v`
Expected: ERROR `ModuleNotFoundError: No module named 'passkeys'`.

- [ ] **Step 3: Implement `passkeys.py`** with the interfaces above. Parse COSE keys into `cryptography` public keys: EC2 uses `-1:1` (P-256), `-2` x and `-3` y (32 bytes each); RSA uses `-1` n and `-2` e. Compare challenges with `hmac.compare_digest`.

- [ ] **Step 4: Run the full Home suite with the venv.** Expected: all OK.

- [ ] **Step 5: Commit** — `Home: passkeys module, WebAuthn checks with cryptography (#6)`

---

### Task 4: Passkey endpoints in Home

**Files:**
- Modify: `stacks/home/server.py`
- Test: `stacks/home/tests/test_routes.py` (new class `PasskeyRoutes`)

**Interfaces:**
- Consumes: everything in Task 3's Produces block; `auth.via_proxy`, `auth.https_on`, `auth.login_cookie`, `THROTTLE`, `login_lock`.
- Produces (HTTP API, all JSON; every endpoint answers 404 unless `auth.https_on()` and `auth.via_proxy(self)`):

| Method, path | Login | Body | Answer |
|---|---|---|---|
| `POST /api/passkey/login/options` | no | `{}` | `{"publicKey": login_options(...)}` |
| `POST /api/passkey/login` | no | `{"id", "clientDataJSON", "authenticatorData", "signature", "remember", "next"}` (base64url) | as `/api/login`: `{"ok": true, "next"}` + cookie; 401 `{"error": "wrong"}`; 429 `{"error": "wait", "retry_after"}` |
| `GET /api/passkeys` | yes | – | `{"passkeys": [{"id", "name", "created", "last_used"}]}` |
| `POST /api/passkeys/options` | yes | `{}` | `{"publicKey": registration_options(...)}` |
| `POST /api/passkeys` | yes | `{"name", "clientDataJSON", "attestationObject"}` | `{"ok": true}`; 400 `{"error": "<user-facing sentence>"}` |
| `POST /api/passkeys/<id>/remove` | yes | `{}` | `{"ok": true}` or 404 |

The JSON-only rule (`refuse_form`) and the `from_another_site` check apply to all of these. A failed passkey login calls `THROTTLE.fail(addr, now)` under `login_lock`, just like a wrong password. `PasskeyError` text is logged with `log("passkey refused:", reason)` and never returned to the client. Module globals: `CHALLENGES = passkeys.Challenges()` and `PASSKEYS = passkeys.Store(passkeys.default_path())`.

- [ ] **Step 1: Write the failing tests.** Reuse the `Authenticator` helper from `test_passkeys.py` (import it). Proxied requests send `X-Forwarded-Proto: https` and `Host: nas.example.ts.net:3443` from 127.0.0.1.

```python
def test_endpoints_are_404_without_a_name_or_not_through_caddy(self): ...
def test_register_then_sign_in_sets_the_cookie(self): ...       # options → register → login options → login → Set-Cookie nas_admin=…; Secure
def test_register_needs_login(self): ...                        # 401
def test_wrong_signature_counts_against_the_throttle(self): ... # 5 bad logins → 429
def test_list_and_remove(self): ...
def test_challenge_from_registration_cannot_sign_in(self): ...  # Review Focus 5
def test_next_is_filtered_by_safe_next(self): ...               # next="https://evil.example/" → "/admin/"
```

- [ ] **Step 2: Run them to verify they fail.** Expected: 404s where 200 is expected.
- [ ] **Step 3: Implement the routes.**
- [ ] **Step 4: Run the full Home suite with the venv.** Expected: all OK.
- [ ] **Step 5: Commit** — `Home: passkey sign-in and management API (#6)`

---

### Task 5: Passkey UI: login dialog and Account settings

**Files:**
- Modify: `stacks/home/static/index.html` (login dialog), `stacks/home/static/guest.js` (login section, line 51+)
- Modify: `stacks/home/static/admin/settings.js` (`drawAccount`, line 192+, and its click handler), `stacks/home/static/admin/settings.css` if needed
- Create: `stacks/home/static/passkey.js`: shared helpers `b64urlToBuf(s)`, `bufToB64url(buf)`, `passkeysAvailable(): Promise<bool>` (`window.PublicKeyCredential` and `isSecureContext`), and `toCreateOptions(json)` / `toGetOptions(json)`, which turn base64url fields into ArrayBuffers.
- Test: `stacks/home/static/lib.test.mjs` pattern → `static/passkey.test.mjs` for the base64url helpers (`node --test`).

**Interfaces:**
- Consumes: the Task 4 API.

**Behaviour:**
- **Login dialog:** when `passkeysAvailable()`, a full-width primary button **"Sign in with passkey"** sits above the password field, with a thin "or" divider. It calls the login options endpoint, then `navigator.credentials.get`, then posts to `/api/passkey/login` with the existing "remember" checkbox and `next`. On success it goes to `next`, like the password flow. A cancelled prompt (`NotAllowedError`) shows nothing; any other failure shows "That passkey didn't work. Use your password." Where `PublicKeyCredential.isConditionalMediationAvailable()` is true, the dialog also starts a conditional `get` (`mediation: "conditional"`, `autocomplete="current-password webauthn"` on the password field). It aborts with an `AbortController` when the button flow starts or the dialog closes.
- **Account section:** a "Passkeys" group comes before "Change password". It holds one row per passkey: name, then "Added <date> · Last used <date or never>" in small text, and a `confirmButton` "Remove". Below the rows: a name field (placeholder "iPhone") and an "Add passkey" button. Off the HTTPS name (no secure context), the group shows one line instead: "Passkeys work on the secure address: open https://…:3443", where the address is built from `location.hostname` only if it ends in `.ts.net`; otherwise the line says "the secure address". Toasts: "Passkey added." / "Passkey removed." / "Couldn't add the passkey." / and the server's 400 sentence when present.
- No nested boxes: rows go in the existing `.group` / `.row` classes.

- [ ] **Step 1: Write the failing JS test** for `bufToB64url(b64urlToBuf("AQID_-8"))` round-trips and for padding-free output. Run `node --test static/passkey.test.mjs`. Expected: FAIL (module missing).
- [ ] **Step 2: Implement `passkey.js`, then the dialog and settings changes.** Run the JS test. Expected: PASS.
- [ ] **Step 3: Visual check:** `scripts/shoot.sh` the login dialog and Settings → Account at 1920×1080, 1800×1125 and 400 px (the secure-address line shows, because the shooter isn't on HTTPS). Look at the screenshots and fix anything crowded or misaligned.
- [ ] **Step 4: Commit** — `Home: passkey button on login, passkeys in Account settings (#6)`

---

### Task 6: Caddy stack, deploy, DNS, docs

**Files:**
- Create: `stacks/caddy/docker-compose.yaml`, `stacks/caddy/Caddyfile`, `stacks/caddy/.env.example` (`NAS_TS_NAME=<nas-name>.<tailnet>.ts.net`)
- Modify: `.gitignore` (`stacks/caddy/data/`, `stacks/caddy/config/`), `README.md`

**Compose:** `image: caddy:<pinned>`, `container_name: caddy`, `restart: unless-stopped`, `network_mode: host`, `env_file: .env`. Volumes:
- `../tailscale/run:/var/run/tailscale` (the folder, so it survives tailscaled restarts)
- `./Caddyfile:/etc/caddy/Caddyfile:ro`
- `./data:/data`
- `./config:/config`

**Caddyfile:**

```
{
	auto_https disable_redirects
}
{$NAS_TS_NAME}:3443 {
	reverse_proxy 127.0.0.1:3001
}
{$NAS_TS_NAME}:8843 {
	reverse_proxy 127.0.0.1:8800
}
{$NAS_TS_NAME}:8793 {
	reverse_proxy 127.0.0.1:8790
}
```

(Caddy's `reverse_proxy` already overwrites `X-Forwarded-Proto` and `X-Forwarded-For` from untrusted clients and keeps `Host`; don't add `trusted_proxies`.)

- [ ] **Step 1: Validate locally:** `docker run --rm -e NAS_TS_NAME=nas.example.ts.net -v $PWD/stacks/caddy/Caddyfile:/etc/caddy/Caddyfile:ro caddy:<pinned> caddy validate --config /etc/caddy/Caddyfile`. Expected: `Valid configuration`. If Docker isn't available on the laptop, run the same command over SSH on the NAS after copying the file.
- [ ] **Step 2: Deploy Caddy (rollout step 3).** Order note: Step 4 below is split. First deploy the new code with `NAS_TS_NAME` empty, then this step, verify `https://NAME:8793` gives `302` and `/api/internal/layout` on :3443 gives `401` (old code trusted all loopback, so Caddy before the new code exposes Netwatch), then Step 3, then set `NAS_TS_NAME` and recreate. Copy `stacks/caddy/` to `/volume1/docker/caddy/`, then write `.env` on the NAS with the real name, taken from `docker exec tailscale tailscale status --json` (`CertDomains[0]`). Don't print the name in any committed file. Then `docker compose up -d`.
  Check from the NAS: `curl -sS -o /dev/null -w "%{http_code} %{ssl_verify_result}\n" --resolve "$NAME:3443:127.0.0.1" https://$NAME:3443/`. Expected: `200 0` (a valid certificate). `docker logs caddy` shows the certificate obtained from Tailscale.
- [ ] **Step 3: AdGuard rewrite (rollout step 3).** Add the DNS rewrite `NAME → 192.168.1.14` through the AdGuard API on `127.0.0.1:8080` (`POST /control/rewrite/add`, credentials from the NAS, never echoed) or ask the user to add it in the UI. Check: `dig +short NAME @192.168.1.14` gives `192.168.1.14`.
- [ ] **Step 4: Deploy Tasks 1–5 (rollout steps 2 and 5: code first with `NAS_TS_NAME` empty, set it last).** Copy the three stacks' changed files, add `NAS_TS_NAME=` to the Home, Mission Control and Netwatch `.env` on the NAS, and rebuild Home (new dependency) and Mission Control web (new `auth.py`). Recreate Netwatch. Check from the laptop on the LAN:
  - `curl -sI http://192.168.1.14:3001/admin/` → `301` to `https://NAME:3443/admin/`
  - `curl -s http://192.168.1.14:3001/api/public/tv` → JSON
  - `curl -sI http://192.168.1.14:3001/tv` → `200`
  - `curl -sI https://NAME:8793/` → `302` to the HTTPS login (no cookie)
  - the same `curl` for Mission Control on `:8843`

  Then run `scripts/sync-from-nas.sh` and check that `git diff` shows no real name.
- [ ] **Step 5: Uptime Kuma** — add an HTTP(s) monitor for `https://NAME:3443/` with the existing ntfy notification. It's configured in the UI or API, not in git.
- [ ] **Step 6: README:**
  - services table: Caddy plus the three HTTPS addresses;
  - network mermaid: Caddy between the devices and the pages;
  - a new "HTTPS and passkeys" subsection under Operations: the user steps (Tailscale HTTPS Certificates, AdGuard rewrite), the plain-HTTP exceptions, and how to add or remove a passkey;
  - Security table: the "Admin login" row (HTTPS, `Secure` cookie, the internal-loopback rule) and a new "Home" row note on the HTTP exceptions;
  - Known issues: devices with secure DNS / Private Relay at home; Caddy down means the admin pages are unreachable, with the Kuma alert;
  - changelog entry **2026-11-13**.
- [ ] **Step 7: User checks (rollout step 5).** The user adds a passkey on iPhone (Face ID) and Mac (Touch ID), then signs in with each: at home without Tailscale, and away with Tailscale. The password login keeps working too. Wait for their confirmation.
- [ ] **Step 8: Commit and open the PR.** Commit: `Caddy: HTTPS on the Tailscale name; README (#6)`. Push `https-passkeys` (ask first) and open a PR against `main` that says `Closes #6`. Note that it is stacked on the `iptv-status` commits.
