# Admin Settings and Container Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containers carry their port in their name, and a Settings page behind the admin login replaces editing feeds, alert numbers, docks and the password by hand, with new containers showing up by themselves.

**Architecture:** Home owns one settings file (`settings.py`) and passes values into the existing pure modules. Mission Control and Netwatch read a small subset from Home over loopback, and fall back to built-in defaults. The login moves from environment variables to a shared file, so password changes apply on all three services without a restart.

**Tech Stack:** Python 3.12 stdlib (`http.server`, `hashlib.scrypt`), vanilla JS modules, Docker Compose. Tests: `python3 -m unittest discover` in each stack, `node --test` for `lib.test.mjs`.

**Spec:** `docs/superpowers/specs/2026-11-07-admin-settings-design.md`

## Global Constraints

- Standard library only. No new packages. No CDN on the Settings page.
- The repo is public: no usernames, ntfy topic, Tailscale details, real torrent or show names, or settings file. Fixtures use made-up names. Commit as `Achar0 <98092805+Achar0@users.noreply.github.com>`, ending each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `scripts/sync-from-nas.sh` fails on code matching `(password|passwd|secret|token|apikey)\s*[:=]\s*value`. In Python, avoid assignments or keyword arguments with those names. The auth file's fields are `hash` and `key`.
- Never print or log the hash, key or passwords. Run NAS commands so that secrets stay on the NAS.
- `auth.py` stays byte-identical in `stacks/home`, `stacks/mission-control/web` and `stacks/netwatch` (a test checks this).
- `sync-from-nas.sh` copies at most three levels deep: Settings files go directly in `stacks/home/static/admin/`.
- Links are stored as port and scheme, never a hostname. Home's read of Docker stays read-only.
- Style: calm Apple HIG, no nested boxes, using `stacks/home/static/style.css` tokens. Check with `scripts/shoot.sh` at 1920×1080, 1800×1125 and 400 px.
- Ask the owner before each push and before applying on the NAS, if they haven't already approved it in the session. Say before recreating AdGuard that house DNS drops for a few seconds.

## Review Focus

- Two tabs saving while the 30-second scan writes must lose nothing. Test in Task 3.
- A hand-edited `settings.json` that is valid JSON with a wrong value (`"hot_c": "hot"`) or a missing section: wrong value means the broken-file path, missing section means defaults for that section, and alerts keep running. Test in Task 3.
- A feed URL that hangs, is huge, or returns an HTML page: a plain error within the existing 10-second limit, nothing added, and nothing from the response echoed. Test in Task 5.
- A container or feed name containing `<script>`, and a typed port such as `"8080/evil"` or `70000`: names render as text, and ports are integers 1–65535 or refused. Test in Tasks 7 and 9.
- The auth file replaced by one with the same size while the services run: the next request must see it. Test in Task 2.

---

## Part 1: first pull request

### Task 1: Rename containers

Branch `rename-containers` from `origin/main`. Commit the spec, this plan and the prototype here too.

**Files:**
- Modify: `container_name` in `stacks/{home,netwatch,dockge,adguard,autobangumi,speedtest-tracker,uptime-kuma,glances,mission-control,homepage,minecraft_server}/docker-compose.yaml`, using the spec's table exactly
- Modify: `stacks/mission-control/web/static/metrics.js` (`adguardhome` → `adguardhome-8080`, `speedtest-tracker` → `speedtest-tracker-8765` in `cpu()`/`ram()`)
- Modify: `README.md` (services, known names, changelog); `stacks/homepage/config/services.yaml` is retired, leave it
- Do not change: `tailscale`, `qbittorrent-app-1`, `firefox-app-1`, `homepage`

**Interfaces:** Produces the container names used by the seed list in Task 3.

- [ ] **Step 1: Edit the names and references.** Run `git grep -n -E '\b(adguardhome|autobangumi|dockerproxy|mc-web|mc-prometheus|mc-collector|mc-node-exporter|mc-smartctl-exporter|uptime-kuma|speedtest-tracker)\b' -- README.md scripts`. Expected: only image names, icons, folder names and URLs remain.
- [ ] **Step 2: Run** `cd stacks/mission-control/collector && python3 -m unittest discover` and `cd stacks/mission-control/web/static && node --test`. Expected: PASS. Fixtures keep their old names.
- [ ] **Step 3: Apply on the NAS.** Copy each compose file and `metrics.js` per `CLAUDE.md`, then run `docker compose up -d` in each stack, with `homepage` first and `adguard` last. Don't start `minecraft_server`.
- [ ] **Step 4: Verify.** `docker ps --format '{{.Names}} {{.Status}}'` shows the new names, all `Up`. Kuma `monitor_status` values are all 1. Mission Control's AdGuard and Speedtest queries return data: `mc_container_cpu_percent{name="adguardhome-8080"}` returns one series after 30 seconds. `home-3001` logs show no `restarts unavailable`.
- [ ] **Step 5: Sync and commit.** Run `NAS=<user>@192.168.1.14 scripts/sync-from-nas.sh`, review `git status`, then commit `Rename containers to name-port`.
- [ ] **Step 6: Open the pull request** with `gh pr create`, after the owner's OK to push. Wait for merge before Part 2.

---

## Part 2: second pull request

Branch `admin-settings` from the updated `origin/main`.

### Task 2: Login in a shared file

**Files:**
- Modify: `stacks/home/auth.py`, copied to the other two stacks
- Modify: `scripts/set-admin-password.py`, `.gitignore` (add `admin-auth/`), the three compose files
- Create: `scripts/migrate-admin-auth.sh`
- Modify tests: `stacks/home/tests/test_auth.py`, `test_routes.py`, `stacks/mission-control/web/tests/test_server.py`, `stacks/netwatch/tests/test_gate.py` (their setup writes a temp auth file instead of setting env vars)

**Interfaces:**
- Produces in `auth.py`: `save(pw_hash: str, key: str) -> None` (atomic: temp file in the same folder, mode 600, `os.replace`), `change_password(current: str, new: str) -> bool`, `log_out_everywhere() -> None`, `was_remembered(cookie_header: str, now: float) -> bool`, `MIN_PASSWORD_LEN = 8`.
- The path comes from env `ADMIN_AUTH_FILE`, default `/admin-auth/auth.json`, read on every call. Format: `{"hash": "...", "key": "..."}`.
- `configured()`, `session_ok()`, `login_ok()`, `login_cookie()` keep their signatures.

- [ ] **Step 1: Write failing tests in `test_auth.py`**

```python
def test_missing_file_refuses_everything(self):      # configured() False, login_ok False, session_ok False
def test_invalid_json_refuses_even_with_env_values(self):
    os.environ["ADMIN_PASSWORD_HASH"] = auth.hash_password("x")
    write_raw(self.path, "{not json")
    self.assertFalse(auth.login_ok("x"))
def test_short_key_refuses(self):                    # key of 31 characters
def test_replaced_file_of_same_size_is_seen(self):   # key A → token valid; save() with same-length key B → token invalid
def test_change_password(self):
    self.assertFalse(auth.change_password("wrong", "newpassword"))
    self.assertFalse(auth.change_password(PW, "short"))
    old = token_for_current_key()
    self.assertTrue(auth.change_password(PW, "newpassword"))
    self.assertTrue(auth.login_ok("newpassword")); self.assertFalse(auth.login_ok(PW))
    self.assertFalse(session_ok_with(old))
def test_log_out_everywhere_keeps_password_changes_key(self):
def test_saved_file_is_mode_600(self):
def test_was_remembered(self):                       # login_cookie(True, now) → True; login_cookie(False, now) → False
```

- [ ] **Step 2: Run** `cd stacks/home && python3 -m unittest tests.test_auth`. Expected: FAIL.
- [ ] **Step 3: Implement.** Cache the parsed file against `(st_ino, st_mtime_ns, st_size)` under a lock, with `os.stat` on each call. Missing or invalid means empty credentials, with no fallback to the environment. Update the docstring and `startup_check` message. Copy `auth.py` to the other two stacks.
- [ ] **Step 4: Update the other test setups, the script and compose.** `set-admin-password.py` prints the JSON. In compose, replace `../admin-auth.env` with a volume: `../admin-auth:/admin-auth` for Home, `../admin-auth:/admin-auth:ro` for `web` and Netwatch. Netwatch keeps its `.env`.
- [ ] **Step 5: Write `scripts/migrate-admin-auth.sh`.** It runs on the NAS with `umask 077`: creates `/volume1/docker/admin-auth/` (mode 700), reads the two values from `admin-auth.env`, writes `auth.json`, prints only `done`, and refuses to overwrite an existing `auth.json`.
- [ ] **Step 6: Run** `python3 -m unittest discover` in all three stacks. Expected: PASS, including the identical-copies test.
- [ ] **Step 7: Commit** `Admin login: move to a shared file that can change without a restart`.

### Task 3: Settings store

**Files:**
- Create: `stacks/home/settings.py`, `stacks/home/tests/test_settings.py`
- Modify: `stacks/home/Dockerfile` (add `settings.py` to `COPY`)

**Interfaces — produces:**
- `settings.Store(path: str, feeds_path: str)` with `.get() -> dict` (deep copy), `.update(fn: Callable[[dict], None]) -> dict` (runs `fn` on a copy under a lock, normalizes, writes atomically, returns the new value; if `fn` returns `False` nothing is written; a `ValueError` from `fn` or normalize leaves everything unchanged), `.problem: str | None`.
- `settings.normalize(raw: dict, defaults: dict) -> dict`: missing sections are filled from defaults, wrong values raise `ValueError`.
- `settings.ALERT_LIMITS = {"free_pct": (5, 50), "service_down_min": (1, 60), "intrusion_min": (1, 60), "hot_c": (40, 70), "slow_pct": (10, 90)}`
- Shape:

```python
{"version": 1,
 "feeds": [{"id", "name", "url", "topic", "lang", "enabled"}],      # id = sha1(url)[:12]
 "alerts": {"free_pct": 15, "service_down_min": 2, "intrusion_min": 3, "hot_c": 50, "slow_pct": 50, "push": True},
 "services": [{"id", "name", "icon", "mono", "port", "scheme", "settings_path", "container",
               "on_dock", "state", "running", "port_options"}],     # list order = dock order; state: known|new|ignored
 "rail": {"nas": [{"id", "show"}], "services": [{"id", "show"}]},
 "cards": [{"id", "show"}],
 "known_containers": None}                                          # None until the first scan
```

- **Seed services**, in order, `on_dock` true except Firefox: `home` (3001, `home-3001`), `mission` (8800, `mc-web-8800`), `adguard` (8080, `adguardhome-8080`, `/#settings`), `qbittorrent` (8888, `qbittorrent-app-1`), `autobangumi` (7892, `autobangumi-7892`), `speedtest` (8765, `speedtest-tracker-8765`, `/admin`), `kuma` (3002, `uptime-kuma-3002`, `/settings/general`), `dockge` (5001, `dockge-5001`, `/settings/general`), `netwatch` (8790, `netwatch-8790`), `glances` (61208, `glances-61208`), `ugos` (https 9443, no container), `firefox` (5888, `firefox-app-1`, off). Names and icons as in today's `DOCK` lists; Firefox and new services use `mdi-view-dashboard.svg`, mono.
- **Rail:** `nas` = `cpu, memory, temperature, free`; `services` = `qbittorrent, adguard, speedtest`. **Cards:** `qbittorrent, adguard, speedtest, tailscale, connections`. All shown.

- [ ] **Step 1: Write failing tests**

```python
def test_first_run_imports_feeds_json_all_enabled(self):
def test_defaults_match_todays_alert_numbers(self):
    self.assertEqual(store.get()["alerts"], {"free_pct": 15, "service_down_min": 2, "intrusion_min": 3,
                                             "hot_c": 50, "slow_pct": 50, "push": True})
def test_survives_reload(self):
def test_corrupt_file_is_kept_aside_and_defaults_used(self):
    # settings.json = "{nope": store.problem set, a settings.json.bad-* file holds the original bytes, get() == defaults
def test_wrong_value_counts_as_corrupt(self):       # {"alerts": {"hot_c": "hot"}}
def test_missing_section_uses_defaults_without_problem(self):
def test_out_of_range_update_changes_nothing(self):
    with self.assertRaises(ValueError):
        store.update(lambda s: s["alerts"].update(hot_c=71))
    self.assertEqual(store.get()["alerts"]["hot_c"], 50)
def test_concurrent_updates_lose_nothing(self):     # 8 threads append 25 distinct feeds each → 200 more feeds
def test_write_failure_keeps_old_value_and_raises_oserror(self):
```

- [ ] **Step 2: Run** `python3 -m unittest tests.test_settings`. Expected: FAIL, no module.
- [ ] **Step 3: Implement** `settings.py`. `normalize` also checks: feed URL scheme `http`/`https`, topic in `tech|markets|discoveries`, lang in `en|it`, port an int 1–65535 or `None`, `scheme` in `http|https`, and that `on_dock` true requires a port.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `Home: settings file with safe defaults`.

### Task 4: Alert numbers and the phone switch

**Files:**
- Modify: `stacks/home/attention.py`, `guest.py`, `server.py`, `static/admin/app.js`, `static/admin/index.html`
- Test: `tests/test_attention.py`, `test_guest.py`, `test_server.py`

**Interfaces:**
- Consumes `Store.get()["alerts"]`.
- Produces `attention.DEFAULT_RULES` (same keys as `alerts` minus `push`), `attention.conditions(inputs, now, rules=DEFAULT_RULES)`, `attention.evaluate(inputs, state, now, rules=DEFAULT_RULES)`, `guest.status(inputs, now, updated, rules=attention.DEFAULT_RULES)`, `guest.summary(..., rules=attention.DEFAULT_RULES)`. `server.STORE` is the module-level `Store`, created at import from `DATA` (creating the folder if needed). `/api/attention` gains `"push": bool`.

- [ ] **Step 1: Write failing tests**

```python
def test_free_space_follows_rule(self):       # free_ratio 0.18: no alert at free_pct 15, alert at free_pct 20
def test_hot_follows_rule(self):              # 55 °C: alert at hot_c 50, none at hot_c 60
def test_slow_follows_rule(self):             # last = 0.6 * median: none at slow_pct 50, alert at slow_pct 70
def test_service_down_urgent_after_follows_rule(self):   # 1 min → urgent after 60 s of live
def test_intrusion_urgent_after_follows_rule(self):
def test_guest_status_uses_the_same_rule(self):          # free_ratio 0.18, free_pct 20 → "Storage needs attention"
def test_push_off_sends_nothing_and_never_sends_later(self):
    # attention_tick with a fake gather, alerts.push False, urgent condition → send_push not called
    # alerts.push True, tick again with the same incident → still not called
def test_attention_api_reports_push_state(self):
```

- [ ] **Step 2: Run** `python3 -m unittest discover`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Replace the constants and the literal `0.15`, `50` and `0.5` with `rules`. Keep `evaluate({}, STATE, now)` working for the re-render path, passing the current rules. In `attention_tick`, send pushes only when `alerts.push` is on. In `app.js`, hide `.t-note` when `push` is false.
- [ ] **Step 4: Run** the tests. Expected: all PASS.
- [ ] **Step 5: Commit** `Home: alert numbers and phone switch come from settings`.

### Task 5: Feeds from settings

**Files:**
- Modify: `stacks/home/feeds.py`, `server.py`
- Test: `tests/test_feeds.py`, `tests/test_settings_api.py` (new, same real-server pattern as `test_routes.py`)

**Interfaces:**
- Produces `feeds.check(data: bytes) -> str` (the feed's cleaned title, or `""`; raises `ValueError` if it isn't RSS or Atom), `server.FEEDS_WAKE: threading.Event`.
- Routes, all behind login: `GET /api/settings` (whole settings plus `"problem"`, without `known_containers`), `POST /api/settings/feeds` `{url, topic, lang}`, `POST /api/settings/feeds/<id>` `{enabled}`, `POST /api/settings/feeds/<id>/remove`.
- Errors: `{"error": "<plain sentence>"}` with 400.

- [ ] **Step 1: Write failing tests**

```python
def test_settings_api_needs_login(self):          # GET and each POST without a cookie → 401
def test_add_feed_uses_its_title(self):           # fake get_limited returns rss_sample.xml
def test_add_feed_falls_back_to_hostname(self):   # feed without a title
def test_add_refuses_html_page(self):             # broken.html → 400, feed count unchanged, body doesn't contain the page's text
def test_add_refuses_timeout_and_oversize(self):  # fake raises TimeoutError / ValueError → 400 with a plain message
def test_add_refuses_duplicate_and_ftp(self):
def test_add_cleans_hostile_title(self):          # <title>&lt;script&gt;x&lt;/script&gt;Name</title> → no "<" in the stored name
def test_disabled_feed_is_not_fetched_and_wakes_refresh(self):
def test_remove_feed(self):
```

- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Test-fetch outside the store lock with `get_limited`. `feeds_tick` reads enabled feeds from `STORE`. Replace the news worker's `time.sleep` with `FEEDS_WAKE.wait(900)` and clear it. Add one `read_json(limit)` helper for POST bodies, used by `login()` as well. Keep `feeds.json` in the image: it is only the seed.
- [ ] **Step 4: Run** `python3 -m unittest discover`. Expected: all PASS.
- [ ] **Step 5: Commit** `Home: manage news feeds through the API`.

### Task 6: Detect new containers

**Files:**
- Create: `stacks/home/discovery.py`, `stacks/home/tests/test_discovery.py`
- Modify: `stacks/home/server.py`, `stacks/home/Dockerfile`

**Interfaces:**
- Produces `discovery.apply(cfg: dict, containers: list | None) -> bool` (mutates `cfg`, True if changed), `discovery.published_ports(container: dict) -> list[int]`, `discovery.name_port(name: str) -> int | None`.
- Consumes the shape from `/containers/json?all=1`. `server.gather_inputs` adds `inputs["containers"]` (list, or `None` when unreadable), and `read_restarts(now, containers)` reuses that list.

- [ ] **Step 1: Write failing tests**, using made-up containers

```python
def test_first_scan_only_records_names(self):         # known_containers None → set; no service added
def test_failed_read_changes_nothing(self):           # apply(cfg, None) is False, cfg unchanged, even on first scan
def test_new_container_appears_off_the_dock(self):    # state "new", on_dock False, running True, id "c-<name>"
def test_one_published_port(self):                    # port filled, port_options empty
def test_loopback_port_ignored_ipv4_ipv6_once(self):
    self.assertEqual(published_ports(c([("127.0.0.1", 2375)])), [])
    self.assertEqual(published_ports(c([("0.0.0.0", 7892), ("::", 7892)])), [7892])
def test_several_ports_ask(self):                     # port None, port_options [3000, 8080]
def test_port_from_name_when_none_published(self):    # "thing-9000" → 9000
def test_name_port_rejects_junk(self):                # "thing", "thing-70000", "app-1" → None (1 is a real number: see Step 3)
def test_no_port_at_all_asks(self):                   # port None, port_options []
def test_gone_or_stopped_marked_not_running(self):    # missing or State "exited" → running False; back → True
def test_known_container_never_reappears_as_new(self):
def test_ignored_stays_ignored(self):
def test_removed_row_comes_back_as_new_if_it_returns(self):
```

- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** `name_port` accepts only a suffix of 2–5 digits with a value of 1–65535, so `qbittorrent-app-1` gives `None`. A friendly name comes from the container name without the port suffix, with `-` and `_` turned into spaces and words capitalized. Removing a service also drops its container from `known_containers`.
- [ ] **Step 4: Wire it in.** In `attention_tick`, after `gather`: `STORE.update(lambda s: discovery.apply(s, inputs.get("containers")))`, which writes only when `apply` returns True. A settings write failure is logged, not fatal. Add `discovery.py` to the Dockerfile's `COPY`.
- [ ] **Step 5: Run** `python3 -m unittest discover`. Expected: all PASS.
- [ ] **Step 6: Commit** `Home: new containers show up in settings`.

### Task 7: Services API and layout

**Files:**
- Modify: `stacks/home/server.py`, `tests/test_settings_api.py`, `tests/test_routes.py`

**Interfaces — produces, behind login unless noted:**
- `POST /api/settings/alerts` (partial `alerts`), `POST /api/settings/services/<id>` (`{name?, port?, on_dock?}`; setting `on_dock` or a port moves `new` to `known`), `POST /api/settings/services/<id>/ignore`, `POST /api/settings/services/<id>/remove`, `POST /api/settings/order` (`{list: "dock"|"rail_nas"|"rail_services"|"cards", ids: [...]}`), `POST /api/settings/show` (`{list, id, show}`, not for `dock`).
- `GET /api/layout`, and `GET /api/internal/layout` (**loopback only**, no login): `{"dock": [{id, name, icon, mono, port, scheme}], "rail": {...}, "cards": [...], "push": bool}`, with `dock` holding on-dock services in order.

- [ ] **Step 1: Write failing tests**

```python
def test_internal_layout_refuses_non_loopback(self):   # patch client address to 192.168.1.20, no cookie → 401
def test_internal_layout_carries_no_private_fields(self):  # no url, known_containers, container, feeds keys
def test_order_must_be_a_permutation(self):            # missing or unknown id → 400, unchanged
def test_order_keeps_new_rows_after_known(self):
def test_bad_ports_refused(self):                      # "8080/evil", 0, 70000, True → 400
def test_cannot_dock_without_a_port(self):
def test_name_limited_and_kept_as_plain_text(self):    # over 40 characters → 400; "<b>" stored as given, rendering is Task 9's
def test_ignore_hides_only_new_rows(self):             # a known service → 400
def test_alert_out_of_range_400(self):
def test_writes_survive_restart(self):                 # new Store on the same path sees them
```

- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** the routes. `LOOPBACK` as in Netwatch. Exclude the `/api/internal/` path from the login check only when the address is loopback; otherwise answer 401.
- [ ] **Step 4: Run** `python3 -m unittest discover`. Expected: all PASS.
- [ ] **Step 5: Commit** `Home: API for services, order and layout`.

### Task 8: Account API

**Files:**
- Modify: `stacks/home/server.py`, `tests/test_routes.py`

**Interfaces:** Consumes the `auth.py` functions from Task 2. Produces `POST /api/account/password` `{current, new}` and `POST /api/account/logout-everywhere`, both behind login.

- [ ] **Step 1: Write failing tests**

```python
def test_change_keeps_this_session_and_ends_others(self):
    # sessions A and B; A changes → 200 with Set-Cookie; A's new cookie works; B → 401
def test_change_keeps_remember_setting(self):      # remembered session → new cookie has Max-Age; otherwise none
def test_wrong_current_is_throttled_like_login(self):   # 5 wrong → 429 with retry_after; password unchanged
def test_short_new_password_400(self):
def test_logout_everywhere_ends_this_session_too(self): # 200 with logout cookie; old cookie → 401
def test_read_only_or_missing_auth_file_says_so(self):  # save raises OSError → 503, password unchanged
def test_account_routes_need_login(self):
```

- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `login_lock` and `THROTTLE` as in `login()`, with the same body limit.
- [ ] **Step 4: Run** `python3 -m unittest discover`. Expected: all PASS.
- [ ] **Step 5: Commit** `Home: change password and log out everywhere`.

### Task 9: Settings page

**Files:**
- Create: `stacks/home/static/admin/settings.html`, `settings.js`, `settings.css`
- Modify: `stacks/home/server.py` (`/admin/settings` serves `settings.html`), `static/admin/index.html` (Settings link next to Log out), `static/lib.js`, `static/lib.test.mjs`, `tests/test_routes.py`
- Reference: `docs/mockups/settings-prototype.html`; the spec wins where they differ

**Interfaces:**
- Consumes Tasks 5, 7 and 8. Use absolute URLs (`/lib.js`, `/style.css`) because the page is served from a path without a trailing slash.
- Produces in `lib.js`: `applyLayout(items, order)` (items in `order`'s sequence, `show: false` left out, unknown ids ignored, items missing from `order` appended) and `moveItem(list, from, to)`.

- [ ] **Step 1: Write failing tests**

```python
def test_settings_page_needs_login(self):   # /admin/settings, /admin/settings.html, /admin/settings.js, /%61dmin/settings → redirect
def test_settings_page_served_when_logged_in(self):
```
```js
test("applyLayout follows order, hides, appends missing, ignores unknown", ...);
test("moveItem moves within bounds and ignores out-of-range", ...);
```

- [ ] **Step 2: Run** `python3 -m unittest tests.test_routes` and `cd static && node --test`. Expected: FAIL.
- [ ] **Step 3: Implement the page.**
  - Two panes; on phones the section list becomes a row across the top.
  - Each change saves at once. On failure, the control goes back and a plain message shows.
  - Every name goes through `esc()` or `textContent`.
  - Notice banner when `problem` is set.
  - **Feeds:** switch, name, topic and language, Remove with a two-step confirm, add form.
  - **Alerts:** steppers limited to the spec's ranges. The phone row says Home and Netwatch are covered and links to Uptime Kuma's `/settings/notifications`.
  - **Services & dock:** three tabs. Every row has up/down buttons and a drag handle, with keyboard and touch working through the buttons. The row's description is the container name, or `:<port>` for `qbittorrent` and `firefox`. A "New" heading with Ignore, rename and port entry, or a choice when `port_options` is set. "Not running" label and Remove.
  - **Apps:** a link per service with a port, using `settings_path`, at the current hostname.
  - **Account:** the password form; Log out everywhere with a two-step confirm, then go to `/`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Add a rendering test for names.** With a stored name of `<img src=x onerror=alert(1)>`, the `scripts/shoot.sh` screenshot shows the literal text and no image is created.
- [ ] **Step 6: Check** with `scripts/shoot.sh` at all three sizes, for all five sections, and fix anything cramped.
- [ ] **Step 7: Commit** `Home: Settings page`.

### Task 10: Pages use the layout

**Files:**
- Modify: `stacks/home/static/admin/app.js`
- Modify: `stacks/mission-control/web/server.py`, `web/static/app.js`, `web/static/cards.js`, `web/static/metrics.js`, `web/static/lib.js`, `web/static/lib.test.mjs`, `web/tests/test_server.py`, `stacks/mission-control/docker-compose.yaml` (`HOME_URL`)
- Modify: `stacks/netwatch/app.py`, `docker-compose.yaml` (`HOME_URL`), `tests/test_gate.py`

**Interfaces:**
- Consumes `/api/internal/layout` and `/api/layout`.
- Produces in Mission Control: `GET /api/layout` (after login, via the existing `proxy()`). Produces in Netwatch: `push_enabled() -> bool` (2-second timeout, `True` on any failure).
- Copy `applyLayout` to Mission Control's `lib.js`.

- [ ] **Step 1: Write failing tests**

```python
# mission-control
def test_layout_needs_login(self):
def test_layout_proxies_home(self):
def test_layout_502_when_home_is_down(self):
# netwatch
def test_push_enabled_follows_home(self):         # fake server {"push": false} → False
def test_push_enabled_true_when_home_is_down(self):
def test_send_alerts_sends_nothing_when_off(self):
```

- [ ] **Step 2: Run** `python3 -m unittest discover` in both stacks. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Both pages draw built-in defaults first, then apply the layout if it arrives.
  - Each dock leaves out its own entry (`home` on Home, `mission` on Mission Control), and builds links with `at(port, scheme)`. Copy `mdi-view-dashboard.svg` into Mission Control's icons if it's missing.
  - On Home, rebuild `RAIL` and `SERVICES` from the layout; tiles are addressed by index, so rebuild before refreshing.
  - In Mission Control, build the rail in a single merged order of `CARDS` and `extraCards`, and skip refreshes for hidden rail cards. Keep the full `CARDS` list for `#card=` links, so a Home rail link still opens a card hidden from the rail. Check the Connections card's preview tolerates being hidden.
  - In Netwatch, check `push_enabled()` at the top of `send_alerts`.
- [ ] **Step 4: Run** the tests, including `node --test`. Expected: all PASS.
- [ ] **Step 5: Commit** `Docks, rail and cards follow Settings; Netwatch honours the phone switch`.

### Task 11: Deploy and verify

**Files:**
- Modify: `README.md` (services, Admin login commands, alert rules, Settings section, changelog), `docs/mockups/public-admin.html` and `docs/mockups/README.md` (Settings built)

- [ ] **Step 1: Migrate the login on the NAS.** Run `scripts/migrate-admin-auth.sh` over SSH. Expected: `done`, and `/volume1/docker/admin-auth/auth.json` has mode 600. Don't delete `admin-auth.env`.
- [ ] **Step 2: Apply.** Copy the three stacks and recreate them with `docker compose up -d --build`. Expected: logs show no "admin login is off", and the existing password still works.
- [ ] **Step 3: Check logged-out access with `curl`.** Every `/api/settings*`, `/api/account/*`, `/api/layout` on Home and Mission Control, and `/api/internal/layout` from the laptop, answers 401; `/admin/settings` redirects to login.
- [ ] **Step 4: Run the spec's checks** in a real browser:
  - add a real feed and a non-feed URL; turn a feed off and confirm it leaves Home and the guest page
  - change a threshold so a condition fires, and confirm the admin alert and guest card follow; restore it
  - reorder the dock, hide a card, and reload Home and Mission Control
  - check the Apps links open the right pages from both the LAN address and Tailscale; fix any `settings_path` that doesn't
- [ ] **Step 5: Test detection.** Start a throwaway container with a published port. Expected: it appears under New within a minute, off the dock. Switch it on and check the link from both addresses. Remove it: "not running". Remove the row.
- [ ] **Step 6: Test the password, with the owner typing it.** The password and its changes are the owner's, so ask them to do this part in the browser. Change it: the old one fails on all three ports, another logged-in browser is logged out, and this one isn't. Log out everywhere logs out both. Confirm `set-admin-password.py` still gets back in.
- [ ] **Step 7: Restart** Home, Mission Control and Netwatch. Expected: settings persist, login works, and with `settings.json` broken on purpose then restored, alerts keep running.
- [ ] **Step 8: Sync and check for leaks.** Run `NAS=<user>@192.168.1.14 scripts/sync-from-nas.sh`. Expected: no scan hits. `git status` shows no `auth.json` or `settings.json`.
- [ ] **Step 9: Update the docs and commit** `Admin Settings: docs and README`.
- [ ] **Step 10: Open the pull request,** with `Closes #3` in the description, after the owner's OK to push. Once the owner confirms all is well, offer to delete the old `admin-auth.env`; don't delete it without asking.
