# Public Summary Page and Admin Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `:3001` becomes a guest summary, the owner's page moves to `:3001/admin`, and one password protects Home's admin side, Mission Control and Netwatch.

**Architecture:** A stdlib-only `auth.py` (one file, copied into each of the three stacks, kept identical by a test) signs and checks a stateless session cookie. Home owns the login. Mission Control and Netwatch only check the cookie and redirect to Home. Guest data comes from one server-built endpoint, never from admin APIs.

**Tech Stack:** Python 3.12 stdlib (`http.server`, `hashlib.scrypt`, `hmac`), vanilla JS modules, Docker Compose. Tests: `python3 -m unittest discover`, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-07-public-summary-design.md`

## Global Constraints

- Standard library only in `auth.py`, `guest.py` and the servers. No new packages.
- Secrets live only in `/volume1/docker/admin-auth.env` (`ADMIN_PASSWORD_HASH`, `SESSION_SECRET`). Never commit, print or log them.
- The repo is public: fixtures use made-up names only (`Example Show`, `Some.Movie.2024.1080p.x265-GRP`). Commit as `Achar0 <98092805+Achar0@users.noreply.github.com>`.
- `scripts/sync-from-nas.sh` fails on code matching `(password|secret|token)\s*[:=]\s*value`. In Python, avoid assignments or keyword arguments named `password`, `secret` or `token`: use `pw`, `key`, `tok`.
- The hash format uses `:` as separator, never `$`, because Compose interpolates `$` in `env_file`.
- Cookie: name `nas_admin`, `HttpOnly; SameSite=Strict; Path=/`, no `Domain`, no `Secure`. With remember: `Max-Age=2592000` and a token valid for 30 days. Without: no `Max-Age` and a token valid for 12 hours.
- Wrong passwords: after 5 failures from one address, wait 30 s, doubling up to 900 s.
- Fail closed: a missing or invalid hash or a `SESSION_SECRET` under 32 characters refuses every login and session. The guest page keeps working.
- Guest copy is exactly as in the spec's status table.
- Screens: calm Apple style, checked with `scripts/shoot.sh` at 1920×1080, 1800×1125 and 400 px.

## Review Focus

- A locked path requested in disguise (`/%61dmin/app.js`, `//admin/`, `/x/../admin/`) or with `HEAD` must be refused like the plain path. Test in Tasks 3 and 5.
- A session expiring while a page is open: the next data call gets 401 and the page should go to login, not sit on stale numbers. Test in Tasks 3 and 5, with the page's reload added in Tasks 4 and 5.
- The attention worker dying or Prometheus answering without its exporters must give "Status unavailable", never "All services are online". Test in Task 2.
- A return address after login pointing elsewhere (`next=http://evil.example/`, `next=//evil.example`, another port, another host) must fall back to `/admin`. Test in Task 1.
- A tampered, expired or malformed cookie, or one signed with an old key, must count as logged out without a server error. Test in Task 1.

---

### Task 1: Shared auth module

**Files:**
- Create: `stacks/home/auth.py`
- Create: `stacks/home/tests/test_auth.py`
- Create: `scripts/set-admin-password.py`
- Create: `stacks/admin-auth.env.example`
- Modify: `.gitignore` (add `admin-auth.env` and `!stacks/home/static/icons/ugos.png`)

**Interfaces:**
- Produces, in `auth.py`:
  - `hash_password(pw: str) -> str`, format `scrypt:<n>:<r>:<p>:<salt hex>:<hash hex>`, n=2**15, r=8, p=1, maxmem 64 MiB
  - `verify_password(pw: str, stored: str) -> bool`, False on a malformed hash
  - `make_token(key: str, expires: int) -> str`, `check_token(key: str, tok: str, now: float) -> bool`
  - `configured() -> bool`, `session_ok(cookie_header: str | None, now: float) -> bool`, which read the env each call
  - `safe_next(url: str | None, hostname: str) -> str`, returns `url` only if it's `http://<hostname>:<3001|8800|8790>/...`, otherwise `/admin/`
  - `login_cookie(remember: bool, now: float) -> str`, `logout_cookie() -> str`
  - `request_hostname(handler) -> str` from the `Host` header, without the port
  - `require_login(handler) -> bool`, which sends 401 JSON for `/api/*` or 302 to `http://<hostname>:3001/?login=1&next=<current url>` (both `Cache-Control: no-store`) and returns False
  - `class Throttle` with `wait(addr, now) -> int`, `fail(addr, now)`, `reset(addr)`

- [ ] **Step 1: Write failing tests** in `test_auth.py`: hash round trip, wrong password, malformed hash and no `$` in the hash; token valid, expired, tampered, wrong key, garbage, empty; `session_ok` false with a short or missing key; `safe_next` accepts all three ports on the same host and rejects `http://evil.example/`, `//evil.example`, `http://<host>:5001/`, `http://<host>@evil.example/`, `javascript:alert(1)` and `None`; `Throttle` gives 0 for 4 failures, 30 after the 5th, 60 after the 6th, caps at 900, and `reset` clears it.
- [ ] **Step 2: Run** `cd stacks/home && python3 -m unittest tests.test_auth`. Expected: FAIL, no module `auth`.
- [ ] **Step 3: Implement `auth.py`** using `hmac.compare_digest` for all comparisons and `urllib.parse.urlsplit` for `safe_next`. Token format: `<expires>.<hmac-sha256 hex>`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Add** `scripts/set-admin-password.py`, which asks twice with `getpass`, prints `ADMIN_PASSWORD_HASH=...` and a new `SESSION_SECRET=...` from `secrets.token_hex(32)`, importing `stacks/home/auth.py`. Add the empty `stacks/admin-auth.env.example`.
- [ ] **Step 6: Commit** `Add shared admin auth module`.

### Task 2: Guest data

**Files:**
- Create: `stacks/home/guest.py`
- Create: `stacks/home/tests/test_guest.py`
- Modify: `stacks/home/attention.py:88-97` (extract the condition loop)
- Modify: `stacks/home/arrivals.py` (`known` flag)
- Modify: `stacks/home/server.py` (`read_prom` gains `free_bytes`; `attention_tick` stores raw inputs)
- Modify: `stacks/home/tests/test_attention.py`, `test_arrivals.py`

**Interfaces:**
- Produces:
  - `attention.conditions(inputs: dict, now: float) -> tuple[dict, set]`, the active conditions by id and the known sources, used by `evaluate`
  - each item of `arrivals.build` gains `known: bool`, true when `_PATH`, `_FANSUB` or `_BATCH` matched
  - `guest.status(inputs: dict | None, now: float, updated: float) -> dict` with `{"state": "ok"|"warn"|"unknown", "title": str, "detail": str}`
  - `guest.downloads(data: dict) -> dict` with `{"arrived": [...], "downloading": [...], "other": int}`, without `known`
  - `guest.summary(inputs, arrivals_data, now, updated) -> dict` with `{"status", "internet_bps", "free_bytes", "downloads"}`
  - `guest.DEMO: dict[str, dict]`, canned statuses keyed `down`, `storage`, `restart`, `slow`, `many`, `unknown`

- [ ] **Step 1: Write failing tests** for `guest.status`, with exact copy:
  - All sources fine: `Everything's running` / `All services are online`.
  - Kuma `{"AdGuard": 0}`: `Ad blocking is down`. An unmapped name: `A service is down`.
  - RAID, failing drive, hot drive (51 °C) or space below 15%: `Storage needs attention`.
  - Restarts `{"x": 3}`: `Something isn't working right now`, with no `x` anywhere in the output.
  - Speed below half the median: `Internet is slow right now`.
  - RAID + Kuma + speed: `Storage needs attention`, detail `and 2 more`.
  - Any of `kuma`, `prom`, `restarts` None with no problem known: `Status unavailable`. A known problem beats unavailable.
  - `prom` present but `free_ratio` or `md_active` None: `Status unavailable`.
  - `inputs` None, or `updated` more than 300 s old: `Status unavailable`.
  - Netwatch full of live intrusions: `Everything's running`, and no IP in the output.
  - `guest.downloads`: `Some.Movie.2024.1080p.x265-GRP` is only counted in `other`; a fansub-style name appears with show and episode.
- [ ] **Step 2: Run** `cd stacks/home && python3 -m unittest tests.test_guest`. Expected: FAIL.
- [ ] **Step 3: Implement.** Severity order: RAID/failing drive, then service down, then restarts, then hot/space, then speed. The mapping is `{"AdGuard": "Ad blocking", "qBittorrent": "Downloads", "Home": "The home page", "AutoBangumi": "Episode tracking", "Speedtest": "Speed test", "Mission Control": "Monitoring", "Netwatch": "Monitoring", "Tailscale": "Remote access"}`, matched case-insensitively. `guest.status` uses `attention.conditions`, so dismissals have no effect, and ignores `netwatch` and `ab_missing`.
- [ ] **Step 4: Update `attention_tick`** to store `LATEST["inputs"] = inputs` and `LATEST["inputs_at"] = now`.
- [ ] **Step 5: Run** `python3 -m unittest discover`. Expected: all PASS, including the existing attention tests.
- [ ] **Step 6: Commit** `Home: guest status and downloads data`.

### Task 3: Home routes and gate

**Files:**
- Move: `stacks/home/static/index.html`, `app.js` to `stacks/home/static/admin/`
- Modify: `stacks/home/server.py`, `stacks/home/Dockerfile` (copy `auth.py`, `guest.py`), `stacks/home/docker-compose.yaml` (`env_file: [.env, ../admin-auth.env]`)
- Create: `stacks/home/tests/test_routes.py`
- Modify: `stacks/home/tests/test_server.py` where it calls now-gated routes

**Interfaces:**
- Consumes: everything in Tasks 1 and 2.
- Produces:
  - `POST /api/login`, JSON `{"pw": str, "remember": bool, "next": str|null}`, body limit 4 KB. Returns 200 `{"ok": true, "next": <safe>}` with cookie, 401 `{"error": "wrong"}`, 429 `{"error": "wait", "retry_after": int}` or 503 `{"error": "not_configured"}`
  - `POST /api/logout`, which clears the cookie and returns 200
  - `GET /api/public/summary[?demo=<key>]`

- [ ] **Step 1: Write failing tests.** Start the server with a test key and hash. As a guest:
  - `/` 200 and contains no `dock`.
  - `/admin/`, `/admin/app.js`, `/%61dmin/app.js`, `//admin/app.js`, `/x/../admin/app.js` and `HEAD /admin/app.js` all 302 to `:3001/?login=1...`.
  - `/api/attention`, `/api/arrivals`, `/api/prom/query?query=up`, `/api/news?topic=opened`, `POST /api/attention/x/ack` and `POST /api/news/x/open` all 401.
  - `/api/news?topic=all` 200 without an `errors` key.
  - `/api/public/summary` 200 and contains neither `203.0.113.7` nor `Some.Movie`, when `LATEST` holds both.

  With the cookie: `/` 302 to `/admin/`; `/?next=http://<host>:8800/` 302 there; `/admin/` 200; `/api/attention` 200; an expired cookie gives 401.

  Login: right password sets the cookie with the exact flags and the 30-day `Max-Age` when remembered, none when not; wrong gives 401; the sixth attempt gives 429; an evil `next` returns `/admin/`; with no env set, 503 and the guest page still 200.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_routes`. Expected: FAIL.
- [ ] **Step 3: Move the files** with `git mv`. Update the paths in `admin/index.html` and `admin/app.js` to `../style.css`, `../lib.js`, `../carousel.js`, `../icons/`.
- [ ] **Step 4: Implement the gate.** Decide on the **resolved** path: `self.translate_path(path)` inside `STATIC/admin` is locked, so encoded and dotted forms can't slip through. Route `do_HEAD` through the same check. Redirect `/admin` to `/admin/`. Send `Cache-Control: no-store` on redirects and `/`.
- [ ] **Step 5: Run** `python3 -m unittest discover`. Expected: all PASS.
- [ ] **Step 6: Commit** `Home: lock the owner's page behind the login`.

### Task 4: Guest page

**Files:**
- Create: `stacks/home/static/index.html`, `guest.js`, `guest.css`, `news.js`, `icons/ugos.png` (32×32, from the NAS favicon; force-allowed by Task 1's `.gitignore` rule)
- Modify: `stacks/home/static/admin/app.js`, `admin/index.html`, `lib.js`, `lib.test.mjs`

**Interfaces:**
- Produces, in `lib.js`: `fmtTB(v)`, `fmtMbps(v)`, moved from `app.js`, and `otherLabel(n) -> string` (`""`, `"1 other download"`, `"3 other downloads"`).
- Produces, in `news.js`: `mountNews({ topics, onOpen }) -> { refresh(keep) }`, extracted from `app.js` lines 115-173, used by both pages. Guests pass no `opened` topic and no `onOpen`. Stories for guests have no `data-open`.

- [ ] **Step 1: Write failing tests** in `lib.test.mjs` for `otherLabel`, `fmtTB(3.2e12) === "3.2 TB"`, `fmtMbps(936e6) === "936 Mb/s"` and null giving `—`.
- [ ] **Step 2: Run** `node --test stacks/home/static/lib.test.mjs`. Expected: FAIL.
- [ ] **Step 3: Implement the helpers.** Run the test. Expected: PASS.
- [ ] **Step 4: Extract `news.js`** and confirm the admin page behaves the same (topics, arrows, swipe, *Opened*).
- [ ] **Step 5: Build the guest page** as in the approved mockup: header, status row, news, downloads, no dock. **Open UGOS** links to `https://${location.hostname}:9443/` in a new tab. The login is a `<dialog>` with a password field (16 px font, `autocomplete="current-password"`), remember checkbox ticked by default, and Log in. It opens from Admin or `?login=1`. It posts to `/api/login` and goes to the returned `next`. Errors read `Wrong password`, `Too many tries. Try again in N s`, `Login isn't set up yet`. Refresh the summary every 30 s, news every 5 min. Downloads empty state: `Nothing new in the last 48 h`.
- [ ] **Step 6: Admin page.** Add a small **Log out** link calling `/api/logout` then going to `/`. In `getJSON`, on 401 call `location.reload()`.
- [ ] **Step 7: Check** locally with fixture data at 1920, 1800 and 400 px, and `?demo=` for each status. Long names must wrap without moving the layout.
- [ ] **Step 8: Run** `node --test stacks/home/static/lib.test.mjs` and `python3 -m unittest discover`. Expected: all PASS.
- [ ] **Step 9: Commit** `Home: guest summary page with UGOS button and login sheet`.

### Task 5: Lock Mission Control and Netwatch

**Files:**
- Create: `stacks/mission-control/web/auth.py`, `stacks/netwatch/auth.py` (exact copies), `stacks/netwatch/tests/__init__.py`, `stacks/netwatch/tests/test_gate.py`
- Modify: `stacks/mission-control/web/server.py`, `web/Dockerfile`, `web/tests/test_server.py`, `web/static/app.js`, `web/static/connections.js`
- Modify: `stacks/mission-control/docker-compose.yaml` (`mc-web`: `env_file: ../admin-auth.env`)
- Modify: `stacks/netwatch/app.py`, `Dockerfile`, `docker-compose.yaml` (`env_file: [.env, ../admin-auth.env]`), `static/index.html`
- Modify: `stacks/home/tests/test_auth.py` (copies are identical)

**Interfaces:**
- Consumes: `auth.require_login(handler)`.
- Produces: Netwatch module constant `LOOPBACK = {"127.0.0.1", "::1"}`, patched to empty in tests that check the gate.

- [ ] **Step 1: Write failing tests.** Mission Control without a cookie: `/`, `/app.js`, `/vendor/x`, `HEAD /` give 302 to `:3001/?login=1&next=...`; `/api/prom/query?query=up` and `/api/netwatch` give 401. With a cookie: `/` 200. Existing tests keep passing by sending a valid cookie. Netwatch, same list plus `/api/state`, with `LOOPBACK` empty; with the real `LOOPBACK`, `/api/state` from `127.0.0.1` is 200 without a cookie. Stub `maxminddb` in `sys.modules` if it isn't installed. `test_auth.py` asserts the three `auth.py` files are byte-identical.
- [ ] **Step 2: Run** both test suites. Expected: FAIL.
- [ ] **Step 3: Implement.** First line of `do_GET` and `do_HEAD` in both handlers: `if not <allowed>: return`. Add `auth.py` to both Dockerfiles. In the pages' fetch helpers, on 401 call `location.reload()`.
- [ ] **Step 4: Run** all suites. Expected: all PASS.
- [ ] **Step 5: Commit** `Lock Mission Control and Netwatch behind the admin login`.

### Task 6: Deploy, Glances and docs

**Files:**
- Modify: `stacks/glances/docker-compose.yaml`, `README.md`, `docs/mockups/public-admin.html`, `docs/mockups/README.md`, `scripts/sync-from-nas.sh` if needed

- [ ] **Step 1: Owner creates the password.** The owner runs `scripts/set-admin-password.py` and saves the output as `/volume1/docker/admin-auth.env` (`chmod 600`). Nothing is pasted into chat.
- [ ] **Step 2: Check before applying.** On the NAS: `home`'s `.env` has `KUMA_API_KEY` (or the card would always say unavailable), the real Kuma monitor names map in `guest.py`, the old Homepage is stopped, and whether any Kuma monitor targets `:8790` or `:8800`.
- [ ] **Step 3: Deploy** Home, Mission Control and Netwatch following `CLAUDE.md` (copy, `docker compose up -d --build`). Then run `scripts/sync-from-nas.sh` and confirm no secrets are flagged.
- [ ] **Step 4: Glances.** Turn on its password with the running image's own option, with the password file under `./data`. The owner types the password. Verify `curl -o /dev/null -w '%{http_code}' http://192.168.1.14:61208/api/4/status` gives 401 and the dock link prompts. If this can't work, stop and report.
- [ ] **Step 5: Verify live**, logged out, from the laptop, with `curl`: every row of the spec's route table, `:8800` and `:8790`, and `HEAD`. The summary has no IP, alert text or raw name.
- [ ] **Step 6: Verify live, logged in, in a browser:** login, `/admin/` with live alerts, `:8800` with globe, `:8790`, log out. Home still gets Netwatch data. Screenshots with `scripts/shoot.sh` at all three sizes.
- [ ] **Step 7: Update docs:** README (services table, Home section, security section, changelog) and the mockup (UGOS button, downloads).
- [ ] **Step 8: Commit and push** the branch, then open a PR with `Closes #1` that lists what remains of #2.
