# Home (info flow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the gethomepage dashboard on :3001 with an own "Home" page: pinned attention (with urgent takeover + ntfy), a two-card news carousel, media arrivals, a compact Mission Control rail and the dock.

**Architecture:** New stack `stacks/home`: one stdlib-only Python process (`server.py` + pure modules `feeds.py`, `attention.py`, `arrivals.py`) serving `static/` and a small JSON API, with background workers and a JSON state file. The front end is vanilla JS that reuses Mission Control's style tokens and dock icons.

**Tech Stack:** Python 3.12 stdlib, vanilla JS (ES modules), `python3 -m unittest`, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-07-home-info-flow-design.md`

## Global Constraints

- Port **3001**, host network. The old `homepage` container is stopped (not deleted). Its `dockerproxy` keeps running.
- Desktop: no page scroll at 1920×1080, 1800×1125 and 1366×768. Phone ≤ 480 px: one column, scrolls.
- All feed and outside text is escaped or stripped to plain text before it reaches `innerHTML`.
- POST endpoints change only `data/state.json`.
- Secrets live only in `stacks/home/.env` on the NAS: `QBT_USER`, `QBT_PASS`, `KUMA_API_KEY`, `AB_USER`, `AB_PASS`. The repo gets `.env.example`.
- `NTFY_URL` is the same topic as Netwatch. Urgent pushes are titled `URGENT: …`, one per incident.
- Colours and type: Mission Control tokens (`--bg #000`, `--card #1c1c1e`, `--tile #2c2c2e`, accent `#0A84FF`, urgent `#FF453A`, normal `#FF9F0A`).

## Review Focus

1. **A feed returns HTML junk, a 404, or an enormous body.** The others still show, and the summary is plain text with no tags or entities. Tests: `test_broken_feed_isolated`, `test_html_stripped` (Task 1).
2. **Intrusion seen only once.** No takeover. Seen for ≥ 3 min: takeover, and exactly one push even across restarts (the state is persisted). Tests: `test_intrusion_needs_3_minutes`, `test_push_once_per_incident` (Task 2).
3. **Problem resolves, then comes back.** The first incident shows as resolved, and the new one alerts again. Test: `test_reoccurrence_alerts_again` (Task 2).
4. **Kuma or AutoBangumi credentials missing.** Their rules are skipped silently, everything else works, and `/api/attention` reports `sources_down`. Test: `test_missing_source_skipped` (Task 2).
5. **Two devices.** A dismissal or acknowledgement on one disappears on the other within one poll (15 s), because state lives on the server. Check: manual, two browsers (Task 4).

---

## File structure

```
stacks/home/
  docker-compose.yaml   .env.example   feeds.json   Dockerfile
  server.py             HTTP + API + workers + state file
  feeds.py              parse RSS/Atom -> items; clean text; dedupe
  attention.py          rules -> items/incidents (pure: inputs in, items out)
  arrivals.py           qBittorrent torrents -> just arrived / downloading
  tests/test_feeds.py   tests/test_attention.py   tests/test_arrivals.py   tests/fixtures/*
  static/index.html  style.css  app.js  carousel.js  lib.js  lib.test.mjs  icons/ (copied)
```

### Task 1: Feeds

**Interfaces:**
- `feeds.parse(xml_bytes, source, topic, lang) -> list[dict]` returns items `{id, title, summary, link, source, topic, lang, published}` (unix seconds).
- `feeds.clean(html) -> str` strips tags, unescapes entities, collapses whitespace and cuts to 600 characters at a word boundary with `…`.
- `feeds.dedupe(items) -> list` merges items whose normalised title is equal, or whose word overlap is > 0.8 within 12 h. Keep the first-published item.
- `feeds.json` holds `[{"name", "url", "topic", "lang"}]` with the 11 feeds from the spec.

- [ ] **Step 1: Tests.** Use fixtures `rss_sample.xml`, `atom_sample.xml` and `broken.html`, saved from real feeds and trimmed.
  - `test_parse_rss`: correct fields and ISO/RFC dates.
  - `test_parse_atom`.
  - `test_html_stripped`: `"<p>A &amp; B<img src=x></p>"` gives `"A & B"`.
  - `test_long_summary_cut`.
  - `test_dedupe_same_story`: "Apple launches M5 chips" vs "Apple launches M5 chip" gives 1 item.
  - `test_broken_feed_isolated`: `fetch_all` with one feed raising returns the others.
- [ ] **Step 2: Implement** `feeds.py` with `xml.etree` and `html.parser`. Add `fetch_all(feeds, fetch)`, where `fetch` is injected for tests.
- [ ] **Step 3:** `python3 -m unittest discover -s tests` passes. Commit "Home: feeds".

### Task 2: Attention rules

**Interfaces:**
- `attention.evaluate(inputs: dict, state: dict, now: float) -> (items: list, urgent: dict|None, pushes: list)`. It updates `state` in place: `first_seen`, `resolved_at`, `pushed`, `dismissed`, `acked`.
- `inputs` keys (each may be `None` if its source is unavailable):
  - `netwatch`: `/api/state`
  - `kuma`: `{monitor_name: status}`, where status 1 = up and 0 = down
  - `prom`: `{"md_active", "md_required", "smart_status": {dev: 0/1}, "drive_temp": {dev: C}, "free_ratio", "speed_last", "speed_median"}`
  - `restarts`: `{container: count_in_10min}`
  - `ab_missing`: `[{"show", "episode", "seen_at"}]`
- Item: `{id, level: "urgent"|"normal", title, detail, source, since, resolved: bool, app_url}`. Ids are stable per condition (e.g. `intrusion:203.0.113.7`, `kuma-down:AdGuard`).

- [ ] **Step 1: Tests**, one per rule row in the spec:
  - `test_intrusion_needs_3_minutes`: an inbound flagged item with `first` 2 min ago is normal; with `first` 3 min ago it is urgent.
  - `test_outgoing_flag_is_normal`.
  - `test_kuma_down_2_minutes_urgent`, and `test_kuma_recovered_is_normal_resolved`.
  - `test_raid_degraded_urgent`, `test_smart_fail_urgent`, `test_restart_loop_urgent`.
  - `test_free_space_low_normal`, `test_slow_speedtest_normal`, `test_hot_drive_normal`, `test_ab_missing_normal`.
  - `test_auto_resolve_kept_24h`: the item is still present with `resolved=True` at +23 h and gone at +25 h.
  - `test_push_once_per_incident`.
  - `test_reoccurrence_alerts_again`.
  - `test_dismissed_hidden`, and `test_acked_urgent_not_shown_as_takeover`.
  - `test_missing_source_skipped`.
- [ ] **Step 2: Implement** pure rules with no I/O.
- [ ] **Step 3:** Tests pass. Commit "Home: attention rules".

### Task 3: Server, workers, arrivals

**Interfaces:**
- `arrivals.build(torrents, now) -> {"arrived": [{show, ep, at}], "downloading": [{show, ep, progress, eta, stalled}]}`. It uses the last 48 h of `completion_on`, parses `content_path` for `Show SxxEyy` and falls back to the torrent name.
- `server.py`:
  - Workers:
    - `feeds` every 900 s;
    - `attention` every 30 s: gathers the inputs, calls `evaluate`, sends pushes with an ntfy POST titled `URGENT: <title>`, and saves the state;
    - `arrivals` every 60 s.
  - API as in the spec. `GET /api/attention` returns `{items, urgent, sources_down}`.
  - `?demo=urgent` makes `/api/attention` return a fake urgent item. It is never pushed and never stored.
  - Prometheus proxy: same allowlist and tests as `mission-control/web/server.py`.

- [ ] **Step 1: Tests.**
  - `test_arrivals_parse_path`, `test_arrivals_fallback_name`, `test_arrivals_window_48h`, `test_stalled`.
  - Server: `test_proxy_allowlist`, `test_dismiss_persists` (temp state file), `test_post_only_known_ids`, `test_demo_never_pushed`.
- [ ] **Step 2: Implement.** Inputs:
  - Netwatch `/api/state`.
  - Kuma `/metrics` with Basic auth `:<KUMA_API_KEY>`. Parse `monitor_status{monitor_name=...}`.
  - Prometheus instant queries.
  - Docker proxy `/containers/json` and `/containers/<id>/json` for `RestartCount`, sampled to compute restarts in 10 min.
  - AutoBangumi: check its API for feed items. If it has none, `ab_missing=None` and record a ruling.
- [ ] **Step 3: Deploy.**
  - Copy the stack and create `.env`: the qBittorrent keys come from Homepage's `.env` without printing; the Kuma key and AutoBangumi login are asked from the user.
  - `docker stop homepage`, then `docker compose up -d --build` in `home`. Port 3001 now serves Home.
  - `curl :3001/api/news | head`, `/api/attention`, `/api/arrivals` all return JSON.
- [ ] **Step 4:** Commit "Home: server, workers, arrivals".

### Task 4: Page

**Interfaces:**
- `lib.js`: `esc`, `formatAgo` (copied from Mission Control), `step(index, delta, count) -> index` (clamped), `visibleCount(width) -> 1|2`.
- `carousel.js`: `mountCarousel(el, {onIndex}) -> {set(items), next(), prev()}`. It handles keys (← →, ignored while typing in inputs), touch swipe (horizontal threshold 40 px, vertical scroll still allowed), and buttons.

- [ ] **Step 1: Tests** (`lib.test.mjs`): `step` clamps at both ends, `visibleCount(1920) === 2`, `visibleCount(400) === 1`, and `esc` escapes.
- [ ] **Step 2: Build the page.**
  - Layout: a grid with the main column, a rail of `minmax(16rem, 19rem)`, and a dock row. The main column rows are: greeting, attention (auto, max 3 rows, then "+N more"), news (1fr), arrivals (auto).
  - Takeover: a full-viewport fixed sheet with `role="alertdialog"`, focus trapped on Acknowledge, shown when `urgent && !acked`.
  - Polling: attention every 15 s, news every 5 min, arrivals every 60 s, rail every 15 s. Everything pauses while the tab is hidden.
- [ ] **Step 3: Verify.**
  - Screenshots with `?static` at 1920×1080, 1366×768 and 400 px; `?static&demo=urgent` at 1920×1080.
  - Two browsers: a dismiss on one disappears on the other.
- [ ] **Step 4:** Commit "Home: page".

### Task 5: Integration and docs

- [ ] Netwatch `LOCAL_SERVICES[3001]` becomes `"Home"`. The Mission Control dock's "Homepage" entry becomes "Home".
- [ ] README: services table, a new "Home" section that replaces the "Dashboard (Homepage)" section and keeps the old one as history, Operations, Security (POST endpoints, state file), and the changelog.
- [ ] Run `sync-from-nas.sh` with `home` added to its list. Its secret check must pass.
- [ ] One real `URGENT: test` ntfy push, with the user's OK. Commit "Home: integration, docs".
