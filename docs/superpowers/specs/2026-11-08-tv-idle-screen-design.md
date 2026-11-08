# TV idle screen (`/tv`): design

Issues: #4 (the page) and #5 (the Fire TV launcher opens it when idle).
Mockup: [`docs/mockups/tv-idle-v2.html`](../../mockups/tv-idle-v2.html). The language layout chosen is "B" below.

## Why

Something pleasant and useful on the TV when nobody is using it, readable at a glance from across the room.

The page is bilingual: Simplified Chinese first, with a small English line underneath.

## Goals

- When the Fire TV is idle, the screen shows the page on its own, with no button to press.
- Someone across the room understands it at a glance.
- It feels like part of the home, not like a monitoring screen.

## Non-goals

- Translating news. Headlines and summaries stay in their original Italian or English.
- Changing the language of Home, Mission Control, Settings or the guest page. They stay in English.
- A night mode. The TV is off when nobody is around.
- Any interaction on the page: no login, no buttons, no focusable elements.

## Anti-goals

It fails, even if it technically works, if it reads like an admin dashboard, needs the remote, shows technical or private details (see `guest.py`), or leaves a blank or broken screen when a data source is down.

## What is on screen

Layout as in the mockup: one 16:9 screen, never scrolling.

| Area | Content |
|---|---|
| Left | Large clock, date, Milan; weather now and the next four 3-hour points; one tip |
| Right | One news card rotating about every 12 s, with a *Next* preview |
| Bottom | Just arrived |
| Status line | **Only when something is wrong** (see below) |

- **Language (layout B):** Simplified Chinese first, with a small English line underneath. Applies to the date, weather description, tip, status line and labels. `lang="zh-CN"` on the page so that Android picks Chinese glyphs rather than Japanese ones, and `lang` set per news item. No web fonts.
- **Clock:** 24-hour, updates by itself from the TV's clock. The date reads like `11月7日 星期五 · 米兰`.
- **News:** from the existing public `/api/news` (all topics). The tag is translated, the source is not: `科技 · TECH · THE VERGE`, `财经 · MARKETS`, `发现 · DISCOVERIES`.
- **Just arrived:** only recognised episodes from `guest.downloads` (at most three, arrived first, then downloading). The "other downloads" count is not shown. The row disappears when empty.
- **Status line:** internet speed and free storage from the mockup are **dropped**, because they only matter to the admin. The line appears only when `guest.status` is `warn`, using fixed Chinese + English text for each message in `guest.py`. `ok` and `unknown` show nothing.
- **Burn-in:** content shifts a few pixels every minute.

## Weather

- New pure module `stacks/home/weather.py` plus a worker in `server.py`, like the other workers.
- Open-Meteo forecast for Milan (no key), fetched **by the NAS every 30 minutes**, so the TV needs no internet access for it. Uses current conditions and hourly temperature, apparent temperature, precipitation probability, weather code, wind and UV index, with `timezone=Europe/Rome`.
- Weather codes map to a fixed table of emoji + Chinese + English. No machine translation.
- If the fetch fails, keep the last data for up to 3 hours, then hide the weather block.

### The tip

One line, at most two items, most useful first. Thresholds are starting values, as named constants, with unit tests.

| Priority | Condition in the window | Chinese / English |
|---|---|---|
| 1 | Fog or ice (weather code, or near-freezing wet conditions) | 路上小心，早点出门 / Leave early, drive carefully |
| 2 | Rain (probability ≥ 50 %) | 记得带伞 / Bring an umbrella |
| 3 | Below 8 °C, or windy | 穿暖和点 / Wear a warm jacket |
| 4 | Sunny and UV ≥ 6 | 戴墨镜，涂防晒 / Sunglasses and sunscreen |
| none | | 天气不错，无需特别准备 / Nice day, nothing special to bring |

**Window:** the next 8 hours. From 18:00, it is tonight and tomorrow until 12:00, because by then tomorrow is what people are planning for.

## How it is served

- `GET /tv` serves `stacks/home/static/tv/index.html`, public, no login (same treatment as the guest page).
- `GET /api/public/tv` returns weather, tip, status and episodes, built on the server so that nothing technical can leak. It reuses `guest.status` and `guest.downloads`. A `?demo=` preview works as on the guest page.
- The page polls every 60 s and fetches news every 15 min. Failed requests keep the last good data on screen.
- The Fire TV WebView is older and weaker than a desktop browser: plain JS and CSS, no libraries, only `transform`/`opacity` animation. Everything inserted into the page is escaped, because news comes from outside.

## Launcher (`tv-vibehack-fire-os`, issue #5)

- The launcher's clock screensaver, on the same idle timer as Amazon's, opens `http://192.168.1.14:3001/tv` full-screen in a WebView.
- Any remote press returns to the launcher.
- If the NAS can't be reached, it falls back to the existing clock.
- **To verify on the device:** Fire OS is set to `sleep_timeout` = 20 min, so the stick could go to sleep while the page is on. The page must stay up for at least 90 minutes.

## Scheduled wake

- **The TV can turn itself on at a configured time** (`wake_hour`, `wake_minute`, `wake_days` in the launcher's `config.xml`, off by default; real values stay in the git-ignored release resources) and show `/tv`.
- The launcher schedules this on the device, so it doesn't depend on the NAS.
- If another app is in use, the page doesn't open. While the NAS can't be reached it shows the clock and retries every 30 s.
- If no remote button is pressed within 90 minutes, the TV goes back to standby. Pressing any button cancels the automatic standby.
- **Tested on the TV:** with the stick asleep the alarm turned the television on over HDMI-CEC and opened the page, and standby turned it off again.
- After a reboot the stick's clock starts wrong, so an alarm can fire as soon as the time syncs. It opens the page only if it really is the scheduled time.

## Left to the builder

- Exact spacing and type sizes, within the repo's calm Apple-HIG style. Check with `scripts/shoot.sh` at 1920×1080 and at the WebView's real viewport on the device.
- Wording of the less common weather strings.

## Definition of done

- Unit tests for `weather.py` (code mapping, each tip rule, the 18:00 window, stale data) and route tests for `/tv` and `/api/public/tv`, including that nothing private leaks.
- Page checked with screenshots using the longest real strings and with each source missing.
- Seen on the actual TV, opened by the idle timer, and still on screen after 90 minutes.
- Scheduled turn-on and automatic standby tested on the actual TV, or reported as not feasible.
- README updated (services, known issues, changelog). No personal data committed.
