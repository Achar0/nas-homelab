# Mission Control — design

Date: 2026-11-06 · Status: approved layout; SMART access approved

## Intent

Homepage is the calm launcher: live numbers, one per card, no history. What it can't answer is
"what happened?": *was the CPU busy all night or did it just spike?* Mission Control is a second,
deeper page for exactly that: **performance over time**, plus the stats of the main hosted
services, in one screen.

It's a **tab the user opens on purpose** (no dedicated monitoring screen), so it should load fast
and reward clicking and hovering. It does not need to be readable from across a room.

## Goals

1. **History of performance.** Every chart opens on the **last 24 h**; a 1H / 24H / 1W / 1M / 1Y
   switch digs back further. Retention: **1 year**.
2. **Hierarchy.** Performance is the main flow and gets the most space and weight; service stats
   come second; Disks and Connections are supporting.
3. **One page, no scrolling on desktop.** Everything fits a 16:9 / 16:10 desktop viewport
   (tested at 1920×1080 and 1800×1125).
4. **Apple style** as the main design and language, the same visual system as Homepage
   (tokens, SF/system font, dark materials, 18 px card radius, one key number per card,
   no nested boxes). Follows the `apple-design` skill and Apple HIG.

## Non-goals

- Replacing Homepage. Homepage stays the launcher; Mission Control gets a dock icon there.
- Alert rules / notifications (ntfy already covers Netwatch; Uptime Kuma covers up/down).
- Controlling anything (restart containers, pause torrents). Read-only.
- Grafana. Its look can't be made to match; it can be added later on the same Prometheus if wanted.

## Anti-goals (failure even if it "works")

- Feels chaotic or dense like a generic Grafana board. The user rejected an earlier "too chaotic"
  Homepage design; calm hierarchy matters more than cramming metrics in.
- Needs scrolling on a desktop monitor.
- Hover tooltips covering titles or values (a real complaint on the old Homepage).
- Noticeably slows the NAS (Intel N100, 8 GB RAM, ~4 GB available today).

## Layout (approved via mockups)

One full-viewport grid: **main flow on the left**, **rail of cards on the right** (~260–300 px).

**Left, main flow, top to bottom**

1. **Header of the selected metric**: label + range ("Processor · last 24 h"), current value
   large, then "avg X · peak Y at HH:MM". Range switch (1H/24H/1W/1M/1Y, segmented control) at
   top right. Default selection: Processor, 24H.
2. **Big chart**: area/line chart that fills the remaining height. Hover (or touch-drag) shows a
   crosshair + value and time at that point, in a readout that never covers the header.
3. **Metric tiles row** (5): Processor, Memory, Temperatures, Disk I/O, Network. Each tile has
   label, current value, 24 h sparkline. Clicking a tile puts it in the big chart; the selected
   tile is highlighted.
   - Temperatures chart: CPU package and NVMe as two lines; drives too.
   - Disk I/O: read and write as two lines. Network: in and out as two lines.
4. **Disks strip** (one line): `RAID 1 (md1)` with health state, `Disk 1` / `Disk 2`
   (Seagate IronWolf 4 TB) and `NVMe` (Crucial P310 500 GB), each with temperature and a health
   dot. Hover/click a disk shows details: power-on hours, reallocated / pending sectors, SMART
   overall status, NVMe percentage used.

**Right rail**

- **Service cards**, one key number each, in this order: qBittorrent (upload speed; sub-line:
  seeding count), AdGuard (blocked %; sub-line: queries in 24 h), Speedtest (last download;
  sub-line: when), Tailscale (devices online).
- **Connections card** at the bottom of the rail, filling the remaining height: small live globe
  + "N live".

**Every rail card can be expanded** (user request). One shared behaviour for all of them:

- Clicking a card **expands it over the left area**: it grows out of the card, the performance
  stats dim behind it, and the rail stays visible with the open card highlighted. ✕, Esc, or
  clicking the same card again sends it back; clicking another card swaps straight to that one.
  Only one card is open at a time. The performance view is always one click away.
- The expanded view uses the same language as the main flow: header (key number large, context
  line), the 1H–1Y range switch, a big chart with hover readout, and a row of a few detail tiles.
  - **qBittorrent**: chart upload/download; tiles: seeding, uploaded today, ratio, container
    CPU / RAM.
  - **AdGuard**: chart queries vs blocked; tiles: blocked %, queries 24 h, avg latency, top
    blocked domain, container CPU / RAM.
  - **Speedtest**: chart download/upload/ping per test; tiles: last down, up, ping, tests in range.
  - **Tailscale**: chart devices online; a short list of devices (name, online, last seen),
    container CPU / RAM.
  - **Connections**: draggable 3D globe filling the area, arcs from home (Milan) to every
    connection, red for flagged IPs, counts (live / in 24 h / flagged). Data from Netwatch's
    existing `/api/state`. No range switch (Netwatch keeps 24 h).

**Phone (≤ 480 px)**: no-scroll applies to desktop only. On phones the same content stacks in one
column (rail after the main flow) and scrolls.

**Motion**: chart transitions on metric/range change; card expand/collapse anchored to the card
(grows from it, shrinks back into it), interruptible. Respect `prefers-reduced-motion`
(cross-fade instead), reduced transparency and increased contrast.

## Architecture

All new stacks under `/volume1/docker/`, mirrored in `stacks/` in this repo, following CLAUDE.md.

| Piece | What | Notes |
|---|---|---|
| `prometheus` | Time-series database, scrape every 15 s, retention 1 y | Bound to LAN/tailnet only; storage in `./data` (not in git) |
| `node-exporter` | Host CPU, memory, load, temps (hwmon), disk I/O, network, md RAID state | Host network + pid, `/proc`, `/sys`, `/` read-only |
| `smartctl-exporter` | SMART for sda, sdb, nvme0 | Needs raw device access (see Risks) |
| `mc-collector` (own, Python, `uv`) | Exposes Prometheus metrics for: per-container CPU/RAM (via existing read-only `dockerproxy`), qBittorrent, AdGuard, Speedtest Tracker, Tailscale peers | Replaces cAdvisor (too heavy for N100) + several single-purpose exporters with one small process; credentials from its own `.env` |
| `mission-control` (own) | Static page + tiny server: serves UI, proxies `/api/prom/*` → Prometheus `query_range`, `/api/netwatch` → Netwatch | Port **8800**; same pattern as Netwatch (vendored JS, no CDN at runtime) |

- Front end: vanilla JS (like Netwatch). Charts: uPlot (small, fast with long series). Globe:
  globe.gl / three.js, vendored into `data/vendor` on first start like Netwatch does with d3.
- Long ranges: the page asks Prometheus with a `step` matched to the range (e.g. 24 h → 1 min,
  1 y → 3 h) so every request returns a few hundred to ~1500 points.
- Homepage: add "Mission Control" to the dock (`bookmarks.yaml`), and its host to the stack's
  allowed origins if needed. Uptime Kuma: add an HTTP monitor for :8800.
- Expected cost: ~300–450 MB RAM total, Prometheus disk ~2–5 GB/year at this scrape set.

## Risks / open points

- **SMART access.** `smartctl` needs raw access to `/dev/sda`, `/dev/sdb`, `/dev/nvme0`
  (`devices:` + `cap_add: SYS_RAWIO`/`SYS_ADMIN`, or `privileged`). This is a long-running
  service, not a workaround for running root commands. **The user approved (2026-11-06)** giving
  `smartctl-exporter` access to exactly those three devices plus `SYS_RAWIO`/`SYS_ADMIN`; no
  `privileged: true`.
- Drive temperatures for sda/sdb may not exist in hwmon without SMART; then they come only from
  smartctl-exporter.
- Prometheus must not be reachable from the internet. There are no router port forwards today;
  keep it that way.

## Calls made by Claude (not discussed with the user)

- Rail services and their key numbers (list above); Minecraft left out because it isn't running.
- No login on the page: LAN + tailnet only, like the other services.
- Tailscale data: start `tailscaled` with `--socket=/var/lib/tailscale/tailscaled.sock` so the
  socket lands in the mounted `./state` folder, and mount that socket read-only into
  `mc-collector` (the docker proxy can't `exec`).
- uPlot for charts, globe.gl for the globe, own collector instead of cAdvisor.

## Left to the builder

Exact chart colours (reuse Homepage tokens: CPU #0A84FF, memory #BF5AF2, temps #FF9F0A,
storage/network #30D158), spacing, type scale, sparkline resolution, polling interval for live
values (suggest 15 s), the empty/loading/error states (must be calm, never a red wall), and
the phone stacking order details.

## Testing

- `scripts/shoot.sh`-style screenshots at 1920×1080, 1800×1125 (must show **no scrollbar**) and
  400 px; each expanded card (all five) at 1920×1080.
- Check each tile/card swaps the big chart and every range returns data.
- Check NAS load after a day: Prometheus RAM, disk usage, CPU.
- README updated (services table, dashboard section, changelog); `sync-from-nas.sh` secret check
  passes before committing.
