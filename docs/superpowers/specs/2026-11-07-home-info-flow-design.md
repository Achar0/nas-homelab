# Home (info flow): design

Date: 2026-11-07 · Status: approved in conversation ("no, continue with ur work")

## Intent

Mission Control now answers "how is the NAS doing?". The landing page (:3001, today the
gethomepage app) becomes the **roundabout**: the place you open in the morning to see what
needs you, what's new in the world, and whether last night's episodes arrived, and from which
you jump anywhere through the dock.

## Goals

1. **Needs attention, pinned on top.** NAS problems sit above everything until dealt with.
   **Urgent** ones take over the whole screen and push a notification to subscribed devices.
2. **Info flow: tech, markets and discoveries news** as flashcards with the feed's own summary,
   from trustworthy English and Italian sources.
3. **Media arrivals:** did the new episodes download?
4. **Compact Mission Control** on the right, linking into it.
5. **Keep the dock** (same apps as today).
6. Same Apple style as Mission Control (dark first, tokens, one key number per card, calm
   hierarchy, no nested boxes); desktop fits one screen without scrolling; phones stack and scroll.

## Non-goals

- AI summaries (decided: feeds' own summaries only; nothing leaves the NAS but feed fetches).
- Controlling services (read-only, like Mission Control).
- Accounts, logins, per-user feeds.

## Anti-goals

- An alert that cries wolf: a takeover must be rare and true, or it will be ignored.
- A noisy feed: duplicates, ads, or a wall of one-line teasers.
- Losing the dock or a link the old Homepage had.

## The page (approved in mockups, combination of A + B)

```
┌───────────────────────────────────────────────┬──────────────┐
│ Good morning                 Fri 7 Nov · 08:12 │              │
│ ▌ Needs attention (pinned, dismissable)        │  CPU   Mem   │
│ News   All · Tech · Markets · Discoveries      │  Temp  Free  │
│ ┌──────────────┐ ┌──────────────┐              │  qBittorrent │
│ │ card         │ │ card         │  ‹ 3/24 ›    │  AdGuard     │
│ └──────────────┘ └──────────────┘              │  Speedtest   │
│ Just arrived  ep · ep · ep (downloading ▬▬▭)   │ Mission Ctrl›│
│                 [ dock: all apps ]                            │
└───────────────────────────────────────────────────────────────┘
```

**Needs attention** (top of the main column, only when there is something):
- One row per item: coloured dot, what happened (one sentence), source, time, ✕ to dismiss.
- An item clears itself when its condition clears, and stays listed as *resolved* (grey) for
  24 h. Dismissals are stored on the NAS, so they sync across devices.

**Urgent takeover:** a full-screen red sheet over the whole page (dock included) with icon,
title, what happened, "A notification was sent to your phone", and two buttons: open the
relevant app, and **Acknowledge** (closes it on every device). It comes back only if the
problem appears again after being resolved.

**News carousel:** two flashcards side by side. ← → buttons, keyboard arrows, and swipe on
touch move **one card** per step. Card: topic + language tag, headline, feed summary (clamped to
~5 lines), source, age, "Read more ↗" (new tab). Filter: All / Tech / Markets / Discoveries.
Counter "3 / 24". Newest first; near-duplicate headlines collapse into one card. Position is
remembered for the session.

**Just arrived:** episodes completed in the last 48 h, newest first, shown as
*Show · SxxEyy · age*, plus anything still downloading with a progress bar and time left
(or "stalled"). Up to one row; more on hover/click is not needed.

**Right rail:** CPU, Memory, Temperature, Free space (2×2), then qBittorrent upload,
AdGuard blocked %, Speedtest last download (one number each), then "Mission Control ›".
Values come from the existing Prometheus (same metrics as Mission Control).

**Dock:** identical to Mission Control's dock, with Mission Control in place of Homepage.

**Phone:** one column: attention, news (one card at a time, swipe), arrivals, rail cards;
dock fixed at the bottom.

## Attention rules (agreed)

| Level | Condition | Source |
|---|---|---|
| **Urgent** | Internet address connecting **in** to a non-torrent port, or a blocklisted address connecting in, **seen for ≥ 3 min** (not one sighting) | Netwatch `/api/state` |
| **Urgent** | Service down **> 2 min** | Uptime Kuma |
| **Urgent** | RAID degraded (`node_md_disks{state="active"} < node_md_disks_required`) | Prometheus |
| **Urgent** | Drive SMART failing (`smartctl_device_smart_status == 0`) | Prometheus |
| **Urgent** | A container restarting repeatedly (≥ 3 restarts in 10 min) | docker proxy |
| Normal | Service went down and came back | Uptime Kuma |
| Normal | Outgoing connection to a flagged address | Netwatch |
| Normal | Free space on /volume1 below 15 % | Prometheus |
| Normal | Latest speed test below 50 % of the 30-day median | Prometheus |
| Normal | Drive hotter than 50 °C | Prometheus |
| Normal | An episode AutoBangumi saw in its feed has not been downloaded after 6 h | AutoBangumi + qBittorrent |

Urgent notifications go to the existing ntfy topic (`NTFY_URL`, same as Uptime Kuma and
Netwatch), titled "URGENT: …", once per incident. Uptime Kuma and Netwatch keep their own
alerts.

## Feeds (verified 2026-11-06: reachable, real summaries)

| Topic | Feeds |
|---|---|
| Tech | The Verge, TechCrunch, Ars Technica, MIT Technology Review, Wired Italia, DDay.it, Il Sole 24 Ore Tecnologia |
| Markets | CNBC Markets, CNBC Technology, Il Sole 24 Ore Finanza |
| Discoveries | ScienceDaily (technology) |

URLs live in a config file in the stack (editable without code changes). Fetched every 15 min,
keep 3 days, at most 60 items in the API. Excluded and why: ANSA (one-line summaries), Hacker
News (no summaries), Yahoo Finance and Milano Finanza (feeds 404), Nature (empty feed).

## Architecture

New stack `home` (replaces the `homepage` container on **:3001**; the old Homepage config stays
in the repo, and its `dockerproxy` service keeps running for Mission Control).

| Piece | What |
|---|---|
| `home` (own Python, stdlib only) | One process: serves the page (`static/`, mounted read-only), the API, and background workers: feeds every 15 min; attention checks every 30 s; arrivals every 60 s. State (dismissals, acknowledged incidents, feed cache) in `data/state.json`. Host network, `PORT=3001`. |
| API | `GET /api/attention` (items + urgent incident), `POST /api/attention/<id>/dismiss`, `POST /api/attention/<id>/ack`, `GET /api/news?topic=`, `GET /api/arrivals`, `GET /api/prom/query` (same read-only allowlist as Mission Control) |
| Inputs | Prometheus 127.0.0.1:9090; Netwatch 127.0.0.1:8790; docker proxy 127.0.0.1:2375; qBittorrent, Uptime Kuma, AutoBangumi with logins in `home/.env` |

The page is vanilla JS + the Mission Control style and dock icons (copied, no CDN).
POST endpoints only change Home's own state file; nothing on the NAS is controlled.

## Constraints

- Desktop (≥ 1024 px): no page scroll at 1920×1080, 1800×1125, 1366×768.
- All outside text is escaped before it reaches `innerHTML` (feed titles and summaries are
  untrusted: strip HTML, keep text).
- Feed fetching: 10 s timeout per feed, honest User-Agent without personal data, one failing
  feed never breaks the others.
- RAM target: < 60 MB for the `home` container.
- Secrets only in `home/.env` (repo has `.env.example`).

## Calls made by Claude

- Replace gethomepage with own code on the same port (it can't do takeover/carousel/pins).
- Uptime Kuma read through its `/metrics` endpoint with an **API key the user creates once**
  (Settings → API Keys); if that is not wanted, fall back to reading `kuma.db` read-only.
- AutoBangumi read through its API with the existing login; if its API can't list feed items,
  the "not downloaded after 6 h" rule is dropped rather than guessed.
- Show/episode for arrivals parsed from the renamed file path (`…/Season N/Show SxxEyy.ext`),
  falling back to the torrent name.
- Duplicate collapse: same normalised headline (lowercase, no punctuation) or > 0.8 word-overlap
  within 12 h.
- Takeover covers the dock too (it's urgent); Esc does not dismiss it, only Acknowledge.

## Left to the builder

Exact spacing and type, card clamp length, empty states ("All quiet" when nothing needs
attention; "No new episodes in 48 h"), carousel animation (spring-like slide, interruptible,
cross-fade under reduced motion), greeting by time of day.

## Testing

- Unit tests (Python `unittest`, `node --test`) for: attention rules (each row of the table,
  including the ≥ 3 min intrusion rule and auto-resolve), feed parsing (RSS and Atom, HTML
  stripping, duplicate collapse, a broken feed), arrivals parsing, escaping.
- Screenshots (`?static`) at 1920×1080, 1366×768, 400 px; takeover state via a test flag
  (`?demo=urgent`, no notification sent).
- A real ntfy test: one "URGENT: test" push after deployment, with the user's OK.
