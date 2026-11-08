# TV idle screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bilingual `/tv` page served by Home that the Fire TV shows when idle and turns on at a configured time.

**Architecture:** A pure `weather.py` and a worker fetch Open-Meteo on the NAS. `guest.tv()` builds a leak-free payload for `GET /api/public/tv`, consumed by a static page at `/tv`. In `tv-vibehack-fire-os`, the screensaver loads that page in a WebView, and a device alarm turns the TV on at the configured time.

**Tech Stack:** Python 3.12 stdlib and `unittest`; plain JS/CSS; Java for Android (minSdk 26, targetSdk 29), JUnit 4.

**Spec:** `docs/superpowers/specs/2026-11-08-tv-idle-screen-design.md`

## Global Constraints

- Home stays standard library only. Tests: `python3 -m unittest discover -s tests` in `stacks/home` (baseline: 282 tests, OK).
- Public repo: no personal data. Fixtures use made-up shows. Commit as `Achar0 <98092805+Achar0@users.noreply.github.com>`, on a feature branch.
- Ask the user before pushing, and before changing any system setting on the TV or NAS.
- Chinese is Simplified, with a small English line underneath. News text is never translated. No web fonts or libraries on the page.
- Page never scrolls and has no focusable elements. Only `transform`/`opacity` animate.
- Update `README.md` (services, known issues, changelog) with the Home change.

## Review Focus

1. Everything fails at first boot (no weather, no arrivals, no inputs): page shows the clock and no broken blocks. Test in Task 2, check in Task 3.
2. A hostile or very long headline: escaped as text and clamped, never pushes the layout off screen. Check in Task 3.
3. The NAS is off when the screensaver starts: the existing clock appears, not an error page. Check in Task 4.
4. A day not in the schedule, or after the last scheduled time: no alarm fires until the next scheduled day. Test in Task 5.
5. The stick reboots or the launcher updates: the alarm is armed again without opening anything. Check in Task 5.

---

### Task 1: Weather module

**Files:**
- Create: `stacks/home/weather.py`
- Test: `stacks/home/tests/test_weather.py`

**Interfaces:**
- Produces: `URL: str`; `build(raw: dict, now: datetime, fetched: float) -> dict` returning `{"now": {"temp", "feels", "icon", "zh", "en"}, "hours": [{"label": "09", "temp", "icon"}] (4 items), "tip": {"icon", "zh", "en"}, "fetched": float}`; `fresh(w: dict | None, now: float) -> dict | None`.

Constants: `RAIN_PROB = 50`, `COLD_C = 8`, `WIND_KMH = 30`, `UV_HIGH = 6`, `MAX_AGE = 3 * 3600`, `WINDOW_H = 8`, `EVENING_FROM = 18`. Fog codes 45, 48; freezing codes 56, 57, 66, 67; sunny codes 0, 1.

`URL` is `https://api.open-meteo.com/v1/forecast?latitude=45.4642&longitude=9.19&current=temperature_2m,apparent_temperature,weather_code&hourly=temperature_2m,precipitation_probability,weather_code,wind_speed_10m,uv_index&timezone=Europe/Rome&forecast_days=3`.

- [ ] **Step 1: Write the failing tests** using a helper `raw(**hourly_overrides)` that makes 72 mild, dry, cloudy hours from `2026-11-07T00:00`.

```python
def tip(now=datetime(2026, 11, 7, 7, 42), **over):
    return weather.build(raw(**over), now, 0)["tip"]

def test_nothing_special(self):
    self.assertEqual(tip()["zh"], "天气不错，无需特别准备")
    self.assertEqual(tip()["en"], "Nice day, nothing special to bring")

def test_rain_at_the_threshold(self):
    self.assertEqual(tip(rain_at={9: 50})["en"], "Bring an umbrella")
    self.assertEqual(tip(rain_at={9: 49})["en"], "Nice day, nothing special to bring")

def test_fog_beats_rain_and_two_items_at_most(self):
    t = tip(code_at={9: 45}, rain_at={10: 80}, temp_at={11: 3}, sun_at={12: 7})
    self.assertEqual(t["en"], "Leave early, drive carefully · Bring an umbrella")
    self.assertEqual(t["zh"], "路上小心，早点出门，记得带伞")

def test_morning_ignores_hours_beyond_the_window(self):
    self.assertEqual(tip(rain_at={16: 90})["en"], "Nice day, nothing special to bring")

def test_from_18_looks_at_tomorrow_until_noon(self):
    at18 = datetime(2026, 11, 7, 18, 0)
    self.assertEqual(tip(now=at18, rain_at={11 + 24: 90})["en"], "Bring an umbrella")
    self.assertEqual(tip(now=at18, rain_at={13 + 24: 90})["en"], "Nice day, nothing special to bring")

def test_hours_are_four_three_hour_points(self):
    w = weather.build(raw(), datetime(2026, 11, 7, 7, 42), 0)
    self.assertEqual([h["label"] for h in w["hours"]], ["09", "12", "15", "18"])

def test_unknown_code_still_renders(self):
    self.assertTrue(weather.build(raw(current_code=999), datetime(2026, 11, 7, 7, 42), 0)["now"]["zh"])

def test_stale_weather_is_dropped(self):
    self.assertIsNone(weather.fresh({"fetched": 0}, 3 * 3600 + 1))
    self.assertIsNotNone(weather.fresh({"fetched": 0}, 3 * 3600))
    self.assertIsNone(weather.fresh(None, 0))
```

- [ ] **Step 2: Run** `python3 -m unittest tests.test_weather` in `stacks/home`. Expected: FAIL, no module `weather`.
- [ ] **Step 3: Implement `build` and `fresh`.** Tip copy is exactly the spec's table. Items are ordered by priority and cut to two; `zh` joined with `，`, `en` with ` · `, `icon` from the first (☂️ 🧥 🕶 🚗, none ✨). Ice is a freezing code, or temperature ≤ 1 °C with rain probability ≥ `RAIN_PROB`. Sun needs a sunny code and UV ≥ `UV_HIGH`. The window starts at the current hour and ends `WINDOW_H` later, or at 12:00 tomorrow from `EVENING_FROM`. Hour points are the next four at 3-hour multiples after now. Weather codes use one table of icon/zh/en for every WMO group, with a neutral fallback for unknown codes.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `Home: weather and what-to-bring tip for the TV page`.

### Task 2: Public TV data and routes

**Files:**
- Modify: `stacks/home/guest.py`, `stacks/home/server.py`, `stacks/home/Dockerfile` (add `weather.py` to `COPY`)
- Test: `stacks/home/tests/test_guest.py`, `stacks/home/tests/test_routes.py`

**Interfaces:**
- Consumes: `weather.URL`, `weather.build`, `weather.fresh`; `server.get_limited(url)`; `server.loop`.
- Produces: `guest.tv(inputs, arrivals_data, weather_data, now, updated, rules=attention.DEFAULT_RULES) -> {"status": {"zh", "en"} | None, "weather": dict | None, "episodes": [{"show", "ep", "at": float | None}]}`; `guest.tv_line(title: str) -> dict`; `GET /tv`; `GET /api/public/tv[?demo=<guest.DEMO key>]`.

Chinese status: `Storage needs attention` 存储需要检查; `Something isn't working right now` 有些服务出了问题; `Internet is slow right now` 网络有点慢. `X is down` becomes `<name>暂时不可用`, with names 广告拦截, 下载, 追剧更新, 测速, 监控, 远程访问, 影音库, 主页, and `A service` 某项服务.

- [ ] **Step 1: Write the failing tests.**

```python
# test_guest.py
def test_tv_hides_status_unless_something_is_wrong(self):
    self.assertIsNone(guest.tv(inputs(), EMPTY, None, NOW, NOW)["status"])
    self.assertIsNone(guest.tv(None, EMPTY, None, NOW, NOW)["status"])  # unknown, first boot

def test_tv_status_is_bilingual(self):
    s = guest.tv(inputs(kuma={"AdGuard": 0}), EMPTY, None, NOW, NOW)["status"]
    self.assertEqual(s, {"zh": "广告拦截暂时不可用", "en": "Ad blocking is down"})

def test_every_status_title_has_chinese(self):
    titles = [guest.STORAGE, guest.BROKEN, guest.SLOW] + [p + " is down" for _, p in guest.PLAIN_NAMES] + ["A service is down"]
    for title in titles:
        self.assertNotEqual(guest.tv_line(title)["zh"], title)

def test_tv_episodes_known_only_three_at_most_arrived_first(self):
    data = {"arrived": [{"show": f"Show {i}", "ep": "E01", "at": NOW, "known": True} for i in range(2)]
                       + [{"show": "Some.Movie", "ep": "", "at": NOW, "known": False}],
            "downloading": [{"show": f"Next {i}", "ep": "E02", "progress": .5, "eta": 9, "stalled": False, "known": True} for i in range(2)]}
    eps = guest.tv(inputs(), data, None, NOW, NOW)["episodes"]
    self.assertEqual([e["show"] for e in eps], ["Show 0", "Show 1", "Next 0"])
    self.assertIsNone(eps[2]["at"])

def test_tv_drops_stale_weather(self):
    self.assertIsNone(guest.tv(inputs(), EMPTY, {"fetched": NOW - 3 * 3600 - 1}, NOW, NOW)["weather"])

# test_routes.py, class GuestRoutes
def test_tv_page_is_public(self):
    status, _, data = self.call("/tv")
    self.assertEqual(status, 200)
    self.assertIn(b'lang="zh-CN"', data)

def test_tv_data_contains_nothing_technical(self):
    # same LATEST setup as test_summary_contains_nothing_technical
    status, _, data = self.call("/api/public/tv")
    self.assertEqual(status, 200)
    for secret in (b"203.0.113.7", b"Some.Movie", b"free_bytes", b"internet_bps"):
        self.assertNotIn(secret, data)

def test_tv_data_at_first_boot(self):
    # LATEST["inputs"] = None, no weather, empty arrivals
    d = json.loads(self.call("/api/public/tv")[2])
    self.assertEqual((d["status"], d["weather"], d["episodes"]), (None, None, []))

def test_tv_demo_overrides_only_the_status(self):
    self.assertEqual(json.loads(self.call("/api/public/tv?demo=slow")[2])["status"]["zh"], "网络有点慢")
```

- [ ] **Step 2: Run** `python3 -m unittest tests.test_guest tests.test_routes`. Expected: the new tests FAIL. `test_tv_page_is_public` stays failing until Task 3 creates the file, so create a minimal `static/tv/index.html` holding `<html lang="zh-CN">` in this task.
- [ ] **Step 3: Implement.** In `guest.py`, add `tv_line` and `tv` (reuse `status` and `downloads`; `tv_line` is the single place for the Chinese copy; `warn` is the only state that gives a line, using its title only). In `server.py`, add `weather_tick()` (`LATEST["weather"] = weather.build(json.loads(get_limited(weather.URL)), datetime.now(), time.time())`, so a failure raises and keeps the old value), run it through `loop` every 1800 s, add `"weather": None` to `LATEST`. Route `/tv` to `static/tv/index.html` directly without a redirect, and add `/api/public/tv` before the `/api/` login check. Use `tv_line(guest.DEMO[...]["title"])` for demo, with `unknown` giving `None`.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests`. Expected: all pass.
- [ ] **Step 5: Commit** `Home: public data and route for the TV page`.

### Task 3: The page

**Files:**
- Modify: `stacks/home/static/tv/index.html`
- Create: `stacks/home/static/tv/tv.css`, `stacks/home/static/tv/tv.js`
- Test: `stacks/home/static/lib.test.mjs` (only if helpers are added to `lib.js`)
- Modify: `README.md`

**Interfaces:**
- Consumes: `GET /api/public/tv`, public `GET /api/news` (`items[].title`, `summary`, `source`, `topic`, `lang`; confirm the field names in `feeds.py`).

Copy: date `11月7日 星期五 · 米兰` with `Friday, 7 November · Milan` beneath; labels `下一条 / Next`, `最新到达 · Just arrived`; tags `科技 · TECH`, `财经 · MARKETS`, `发现 · DISCOVERIES`, then the source in capitals. Times: `N 小时前`, `昨天`, `下载中`.

- [ ] **Step 1: Build the page** from layout B in the spec, without the internet/free-space figures. Sizes in viewport units so it fits any WebView size. Headline clamped to 3 lines, summary to 3. Insert all outside text with `textContent`. Empty blocks (weather, status, episodes, news) are hidden.
- [ ] **Step 2: Add behaviour.** Clock updates every second; news rotates every 12 s; `/api/public/tv` polled every 60 s; news every 15 min; a failed fetch keeps what's on screen; content shifts by up to a few pixels every minute with `transform`.
- [ ] **Step 3: Verify in a real browser** with the server running locally: at 1920×1080 and 960×540, with normal data, a very long headline, `<img src=x onerror=alert(1)>` as a headline (renders as text), each `?demo=` state, and at first boot. Expected: no scrolling, no overflow, no broken blocks.
- [ ] **Step 4: Deploy to the NAS** following `CLAUDE.md` (the SSH username is needed from the user), rebuild `home-3001`, run `scripts/sync-from-nas.sh`. Expected: `http://192.168.1.14:3001/tv` responds 200 and weather is non-null after one tick.
- [ ] **Step 5: Update `README.md`**, then commit `Home: bilingual /tv idle page (closes #4)`.

### Task 4: Screensaver opens the page

Work in a clone at `~/Projects/tv-vibehack-fire-os`, on a feature branch.

**Files:**
- Create: `launcher/app/src/main/res/xml/network_security_config.xml`, `launcher/app/src/main/res/layout/dream_web.xml`
- Modify: `launcher/app/src/main/java/com/gathin/tvhome/ClockDream.java`, `launcher/app/src/main/AndroidManifest.xml`
- Docs: `README.md`, `docs/what-we-did.md`

**Interfaces:**
- Produces: `ClockDream.TV_URL = "http://192.168.1.14:3001/tv"`, used by Task 5.

- [ ] **Step 1: Allow plain HTTP only to the NAS** through a network security config permitting cleartext for `192.168.1.14`, referenced from the manifest (targetSdk 29 blocks it by default).
- [ ] **Step 2: Load the page in `ClockDream`.** Show a JS-enabled WebView over the existing clock layout, kept hidden until `onPageFinished`. On a main-frame error or a 10 s timeout, remove it and leave the clock running. Destroy the WebView in `onDreamingStopped`. Keep `setInteractive(false)`, so any key exits. Don't fall back from a working page if a later poll fails; the page handles that itself. Use `setScreenBright(true)` while the page shows.
- [ ] **Step 3: Install and test** with `TV_HOST=192.168.1.10 launcher/build-and-install-firetv.sh`, then `adb shell am start -n com.android.systemui/.Somnambulator`. Expected: page full-screen, Chinese glyphs correct; any remote key returns; with the page URL blocked, the clock appears.
- [ ] **Step 4: Measure how long it stays up.** Leave it idle for 90 minutes and log `dumpsys power | grep mWakefulness` once a minute. Expected without changes: asleep around `sleep_timeout` (20 min). If so, **ask the user**, then set `sleep_timeout` to `5400000` and repeat. Expected: still `Dreaming` at 90 minutes. If Fire OS clamps it, report back before trying anything else.
- [ ] **Step 5: Update the launcher docs** (it now also makes a LAN request), then commit `Screensaver opens the NAS TV page, falling back to the clock`.

### Task 5: Scheduled turn-on

**This task starts with a test on the real TV. If Step 1 fails, stop and report: the spec drops this part.**

**Files:**
- Create: `launcher/app/src/main/java/com/gathin/tvhome/WakeSchedule.java`, `WakeReceiver.java`, `TvPageActivity.java`
- Modify: `TvAccessibilityService.java`, `AndroidManifest.xml`
- Test: `launcher/app/src/test/java/com/gathin/tvhome/WakeScheduleTest.java`

**Interfaces:**
- Consumes: `ClockDream.TV_URL`.
- Produces: `WakeSchedule.next(Calendar now) -> Calendar`, `WakeSchedule.arm(Context)`.

Constants: `wake_hour`, `wake_minute`, `wake_days` in `config.xml` (off by default), `STANDBY_AFTER_MS = 90 * 60_000L`.

- [ ] **Step 1: Prove it works on the TV, with the user watching.** Put the stick to sleep with a delayed wake: `adb shell 'nohup sh -c "sleep 120; input keyevent KEYCODE_WAKEUP" >/dev/null 2>&1 &'`, then `adb shell input keyevent KEYCODE_SLEEP`. Expected: the television itself turns on and switches input. Then test standby through a build calling `performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN)` from the accessibility service. Expected: the television goes off. Record both results in the spec.
- [ ] **Step 2: Write the failing test.**

Cover: before the time, exactly at the time, a day not listed, wrapping to next week (see `WakeScheduleTest`, with made-up times).

- [ ] **Step 3: Run** `./gradlew testDebugUnitTest` in `launcher/`. Expected: FAIL, class missing.
- [ ] **Step 4: Implement.** `arm` uses `AlarmManager.setExactAndAllowWhileIdle(RTC_WAKEUP, …)` to `WakeReceiver`. It is called from `TvAccessibilityService.onServiceConnected` (which runs after boot and reinstall) and from the receiver after firing. The receiver takes a `SCREEN_BRIGHT_WAKE_LOCK | ACQUIRE_CAUSES_WAKEUP` for 10 s (needs `WAKE_LOCK`) and starts `TvPageActivity`: full-screen WebView on `TV_URL`, `FLAG_KEEP_SCREEN_ON`, any key finishes it and cancels standby. After `STANDBY_AFTER_MS` without a key, it finishes and triggers the action verified in Step 1.
- [ ] **Step 5: Run** `./gradlew testDebugUnitTest`. Expected: PASS.
- [ ] **Step 6: Test on the TV.** Temporarily arm for 3 minutes ahead with the stick asleep. Expected: TV on, page visible. Reboot the stick and check `adb shell dumpsys alarm | grep tvhome` shows the next scheduled time. Run the standby path with a shortened delay, then restore the constants.
- [ ] **Step 7: Update the docs**, then commit `Scheduled wake: turn the TV on and show the NAS page (closes nas-homelab#5)`.
