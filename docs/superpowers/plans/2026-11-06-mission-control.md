# Mission Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-screen Apple-style page on the NAS (`:8800`) with 1-year performance history and expandable service cards.

**Architecture:** One new stack `mission-control` with five services: Prometheus (storage), node-exporter and smartctl-exporter (host and disks), `collector` (own Python, service and container metrics), and `web` (own Python, serves the page and proxies a few read-only Prometheus/Netwatch calls). Everything runs with host networking and listens on `127.0.0.1`, except `web`, which listens on `0.0.0.0:8800`. The front end is vanilla JS with uPlot (charts) and globe.gl (globe). Both libraries are vendored into `data/vendor` on first start, the same way Netwatch does it.

**Tech Stack:** Docker Compose, Prometheus v3, node-exporter, smartctl-exporter, Python 3.12 stdlib (no pip deps), uPlot 1.6.31, globe.gl 2.41.x, `node --test` and `python3 -m unittest` for tests.

**Spec:** `docs/superpowers/specs/2026-11-06-mission-control-design.md`

## Global Constraints

- Desktop (≥ 1024 px wide): **no page scroll**, at 1920×1080 and 1800×1125. Phone (≤ 480 px): one column, scrolls.
- Default view: **Processor, 24H**. Range switch values exactly `1H 24H 1W 1M 1Y`. Retention `365d`.
- Colours: CPU `#0A84FF`, memory `#BF5AF2`, temps `#FF9F0A`, network/storage `#30D158`, flagged `#FF453A`. These are Homepage tokens, so the two pages match. Font: system-ui. Card radius 18 px. One key number per card. No nested boxes.
- Hover readouts must never cover a title or a key value.
- Read-only: no endpoint changes anything on the NAS.
- Secrets only in `stacks/mission-control/.env` on the NAS (in git: `.env.example`). Never print or commit them.
- smartctl-exporter: `devices` `/dev/sda`, `/dev/sdb`, `/dev/nvme0` and `cap_add: [SYS_RAWIO, SYS_ADMIN]` only. **Never `privileged: true`.**
- Copy to the NAS with `ssh <user>@192.168.1.14 'cat > file' < local` or tar over ssh (scp fails under /volume1).
- Respect `prefers-reduced-motion`, `prefers-reduced-transparency` and `prefers-contrast`.

## Review Focus

1. **A source is down** (qBittorrent stopped, AdGuard restarting). The collector must still serve every other metric, with `mc_up{source="..."} 0`. The card shows "—" calmly, not an error wall. Tests: `test_source_failure_isolated` (Task 2); card "—" state (Task 5).
2. **A range with no data yet** (1Y on day one). The chart draws whatever exists, with no "NaN" and no blank crash. The header avg/peak uses only real points. Test: `summary ignores nulls` (Task 4).
3. **A short or awkward window** (1366×768 laptop, or a browser with the bookmarks bar). The page must still not scroll: the chart shrinks, tiles keep their size. Check: screenshot at 1366×768 (Task 6).
4. **Bytes vs bits.** Speedtest is in bits/s and network is in bytes/s. Mixing them up shows 8× wrong numbers. Tests: `formatBitrate`/`formatBytes` (Task 4) and the fixture-based speedtest parser test (Task 2).
5. **Proxy abuse.** `/api/prom/*` must only allow `query` and `query_range` GETs, never `/api/v1/admin/*`. Test: `test_proxy_allowlist` (Task 3).

---

## File Structure

```
stacks/mission-control/
  docker-compose.yaml        prometheus, node-exporter, smartctl-exporter, collector, web
  prometheus.yml             scrape config
  .env.example               QBT_USER, QBT_PASS, ADGUARD_USER, ADGUARD_PASS, SPEEDTEST_KEY
  collector/
    Dockerfile
    collector.py             HTTP :9101/metrics, polls sources every 15 s
    sources.py               one parse function per source: API JSON -> list[Metric]
    tests/test_sources.py    unittest, uses fixtures/
    tests/fixtures/*.json    real API responses captured in Task 2 (secrets scrubbed)
  web/
    Dockerfile
    server.py                static files, /vendor/*, /api/prom/*, /api/netwatch
    tests/test_server.py
    static/
      index.html             layout skeleton
      style.css              tokens + layout (no-scroll grid)
      lib.js                 pure helpers (ranges, formatters, summaries) - testable
      lib.test.mjs           node --test
      metrics.js             metric + card definitions (PromQL, colours, units)
      app.js                 state, fetching, rendering, card expansion
      globe.js               Connections expanded view
stacks/tailscale/docker-compose.yaml   modified: socket path
stacks/homepage/docker-compose.yaml    modified: publish dockerproxy on 127.0.0.1:2375
stacks/homepage/config/bookmarks.yaml  modified: dock entry
README.md                              modified
```

## Metric names (shared contract between Task 2 and Task 4)

The collector exposes exactly these (gauges unless noted):

| Metric | Labels | Meaning |
|---|---|---|
| `mc_up` | `source` (`docker`,`qbittorrent`,`adguard`,`speedtest`,`tailscale`) | 1 if the last poll of that source worked |
| `mc_container_cpu_percent` | `name` | % of one host (0–100 over all cores) |
| `mc_container_memory_bytes` | `name` | usage minus cache (`inactive_file`) |
| `mc_qbt_upload_bytes_per_second`, `mc_qbt_download_bytes_per_second` | – | from `/api/v2/transfer/info` |
| `mc_qbt_seeding` | – | torrents in states `uploading`, `stalledUP`, `queuedUP`, `forcedUP` |
| `mc_qbt_uploaded_session_bytes` | – | `up_info_data` |
| `mc_qbt_ratio` | – | `server_state.global_ratio` from `/api/v2/sync/maindata` |
| `mc_adguard_queries_24h`, `mc_adguard_blocked_24h` | – | `num_dns_queries`, `num_blocked_filtering` from `/control/stats` |
| `mc_adguard_latency_seconds` | – | `avg_processing_time` |
| `mc_adguard_top_blocked` | `domain` | value 1, first entry of `top_blocked_domains` |
| `mc_speedtest_download_bits_per_second`, `mc_speedtest_upload_bits_per_second`, `mc_speedtest_ping_ms` | – | latest result |
| `mc_speedtest_last_timestamp_seconds` | – | unix time of latest result |
| `mc_tailscale_peers_online` | – | count of `Peer[*].Online` + self |
| `mc_tailscale_peer_online` | `name`, `os` | 1/0 per device (self included) |
| `mc_tailscale_peer_last_seen_seconds` | `name` | unix time of `LastSeen` (now if online) |

---

### Task 1: Data backbone (Prometheus + exporters)

**Files:**
- Create: `stacks/mission-control/docker-compose.yaml`, `stacks/mission-control/prometheus.yml`, `stacks/mission-control/.env.example`
- Modify: `stacks/homepage/docker-compose.yaml` (add `ports: ["127.0.0.1:2375:2375"]` to `dockerproxy`)
- Modify: `stacks/tailscale/docker-compose.yaml` (entrypoint gets `--socket=/var/lib/tailscale/tailscaled.sock`)

**Interfaces:**
- Produces: Prometheus at `127.0.0.1:9090`, jobs `node` (`127.0.0.1:9100`), `smart` (`127.0.0.1:9633`), `collector` (`127.0.0.1:9101`, defined now, up after Task 2). Docker API at `127.0.0.1:2375` (read-only proxy). Tailscale socket at `/volume1/docker/tailscale/state/tailscaled.sock`.

- [ ] **Step 1: Write the compose file.**
  - `prometheus`: `prom/prometheus:v3.5.0`, flags `--config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --storage.tsdb.retention.time=365d --web.listen-address=127.0.0.1:9090`, volumes `./prometheus.yml:ro` and `./data/prometheus:/prometheus`, `user: "1000:10"`.
  - `node-exporter`: `prom/node-exporter:v1.9.1`, `pid: host`, `/:/host:ro,rslave`, `--path.rootfs=/host --web.listen-address=127.0.0.1:9100 --collector.mdadm --collector.hwmon`.
  - `smartctl-exporter`: `prometheuscommunity/smartctl-exporter:v0.14.0`, `--web.listen-address=127.0.0.1:9633`, devices and caps exactly as in Global Constraints, `user: root` (needed for raw device ioctl inside the container only).
  - All of them: `network_mode: host`, `restart: unless-stopped`.
  - Scrape interval 15 s.

- [ ] **Step 2: Deploy and apply.**
  - Copy the files to `/volume1/docker/mission-control/` and `mkdir -p data/prometheus`.
  - Recreate the homepage stack (`docker compose up -d`) and the tailscale stack.
  - Then `docker compose up -d` in mission-control.

- [ ] **Step 3: Verify.**
  - Run: `ssh <user>@192.168.1.14 'curl -s 127.0.0.1:9090/api/v1/targets | python3 -c "import json,sys;[print(t[\"labels\"][\"job\"],t[\"health\"]) for t in json.load(sys.stdin)[\"data\"][\"activeTargets\"]]"'`
  - Expected: `node up`, `smart up`, `collector down` (not built yet).
  - Also check that `smartctl_device_temperature` has series for sda, sdb and nvme0, and that `node_md_disks` exists for `md1`.
  - `docker exec tailscale tailscale status` still works.
  - `curl -s 127.0.0.1:2375/containers/json` returns a list.
  - Homepage container widgets still work.

- [ ] **Step 4: Commit**
  ```bash
  git add stacks/mission-control stacks/homepage/docker-compose.yaml stacks/tailscale/docker-compose.yaml
  git commit -m "Mission Control: Prometheus, node and SMART exporters"
  ```

### Task 2: Collector

**Files:**
- Create: `stacks/mission-control/collector/{Dockerfile,collector.py,sources.py}`, `collector/tests/test_sources.py`, `collector/tests/fixtures/*.json`
- Modify: `stacks/mission-control/docker-compose.yaml` (add `collector`: `build: ./collector`, image `mc-collector:local`, host network, `env_file: .env`, env `DOCKER_URL=http://127.0.0.1:2375`, `QBT_URL=http://127.0.0.1:8888`, `ADGUARD_URL=http://127.0.0.1:8080`, `SPEEDTEST_URL=http://127.0.0.1:8765`, `TAILSCALE_SOCKET=/ts/tailscaled.sock`, volume `/volume1/docker/tailscale/state/tailscaled.sock:/ts/tailscaled.sock`)

**Interfaces:**
- Consumes: the endpoints from Task 1.
- Produces: `GET 127.0.0.1:9101/metrics` in Prometheus text format, with exactly the metrics in the table above.
- `sources.py`: `Metric = tuple[str, dict[str, str], float]`, plus these pure functions (no I/O):
  - `parse_docker(containers: list, stats: dict[str, dict]) -> list[Metric]`
  - `parse_qbt(transfer: dict, torrents: list, maindata: dict) -> list[Metric]`
  - `parse_adguard(stats: dict) -> list[Metric]`
  - `parse_speedtest(latest: dict) -> list[Metric]`
  - `parse_tailscale(status: dict, now: float) -> list[Metric]`
  - `render(metrics: list[Metric]) -> str`, which escapes label values and writes one `# TYPE x gauge` line per name.

- [ ] **Step 1: Capture fixtures.** Save one real response from each API into `tests/fixtures/`, with credentials from the NAS `.env` and never printed. Replace hostnames, IPs and tailnet names with placeholders. The files:
  - `docker_containers.json` and `docker_stats_adguardhome.json`
  - `qbt_transfer.json`, `qbt_torrents.json` (trimmed to 3 torrents) and `qbt_maindata.json` (only `server_state`)
  - `adguard_stats.json`
  - `speedtest_latest.json` (`/api/v1/results/latest`, Bearer `SPEEDTEST_KEY`)
  - `tailscale_status.json` (`/localapi/v0/status` over the socket, Host header `local-tailscaled.sock`)

- [ ] **Step 2: Write failing tests** in `tests/test_sources.py` (`unittest`):
  - `test_docker_cpu_percent`: hand-made stats where `cpu_delta=2e8`, `system_delta=4e9`, `online_cpus=4`. Expect `mc_container_cpu_percent{name="adguardhome"} == 5.0` (cpu_delta/system_delta×100; already a share of the whole host).
  - `test_docker_memory_minus_cache`: `usage=700e6`, `stats.inactive_file=100e6` gives `600e6`.
  - `test_qbt`: from the fixtures, upload speed equals `transfer["up_info_speed"]`, and the seeding count matches the fixture's states.
  - `test_adguard`: fixture values map 1:1. `mc_adguard_top_blocked` has the first domain as its label.
  - `test_speedtest_units`: from the fixture, `mc_speedtest_download_bits_per_second` equals the fixture's download in **bits/s**. Read the field meaning off the fixture: if the API gives bytes/s, multiply by 8, and write the conversion as a comment in the code.
  - `test_tailscale`: online count equals the online peers + 1 (self). Offline peers have `last_seen` from `LastSeen`.
  - `test_render_escapes`: a label value with `"` and `\` is escaped. The output contains each `# TYPE` once.
  - `test_source_failure_isolated`: `collect_all(fetchers)`, where one fetcher raises, still returns the others' metrics plus `mc_up{source=X} 0`.

- [ ] **Step 3: Run tests**
  - Run: `cd stacks/mission-control/collector && python3 -m unittest -v`
  - Expected: FAIL (functions missing).

- [ ] **Step 4: Implement `sources.py` and `collector.py`.**
  - `collector.collect_all(fetchers: dict[str, Callable[[], list[Metric]]]) -> list[Metric]` wraps each fetcher in try/except and adds `mc_up`.
  - A background thread refreshes every 15 s, and `/metrics` serves the last result. Docker stats use `?stream=false&one-shot=false` so `precpu_stats` is filled.
  - The qBittorrent login keeps its cookie and logs in again on 403.
  - Dockerfile: `python:3.12-slim`, `USER 1000:10`, `CMD ["python","-u","collector.py"]`.

- [ ] **Step 5: Run tests.** Expected: all PASS.

- [ ] **Step 6: Deploy and verify.**
  - Create the NAS `.env`: the user fills in the values. Ask them to, or copy the matching keys from Homepage's `.env` with a script that prints nothing.
  - Then run `docker compose up -d --build collector`.
  - Expected: `curl -s 127.0.0.1:9101/metrics | grep mc_up` shows all five sources at `1`, and the Prometheus target `collector` is `up`.

- [ ] **Step 7: Commit** (`collector/`, compose, `.env.example`). Message: "Mission Control: metrics collector".

### Task 3: Web server

**Files:**
- Create: `stacks/mission-control/web/{Dockerfile,server.py}`, `web/tests/test_server.py`
- Modify: compose, adding `web`:
  - `build: ./web`, image `mc-web:local`, host network;
  - env `PORT=8800`, `PROM_URL=http://127.0.0.1:9090`, `NETWATCH_URL=http://127.0.0.1:8790`;
  - volumes `./data/vendor:/data/vendor` and `./web/static:/app/static:ro`.

**Interfaces:**
- Produces for the front end:
  - `GET /` and static files
  - `GET /vendor/<name>`
  - `GET /api/prom/query?query=…[&time=…]` and `GET /api/prom/query_range?query=…&start=…&end=…&step=…`: passed through to Prometheus `/api/v1/...` unchanged (JSON)
  - `GET /api/netwatch`: Netwatch's `/api/state` JSON, passed through
- `server.py`:
  - `prom_target(path: str, qs: str) -> str | None`: the upstream URL, or `None` if not allowed
  - `VENDOR = {"uPlot.iife.min.js": "https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.iife.min.js", "uPlot.min.css": "https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.min.css", "globe.gl.min.js": "https://cdn.jsdelivr.net/npm/globe.gl@2.41.4/dist/globe.gl.min.js", "countries-110m.json": "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json"}`, downloaded once into `/data/vendor` like Netwatch's `ensure_vendor()`. Verify that each version exists and is at least two weeks old before pinning it.

- [ ] **Step 1: Failing tests.**
  - `test_proxy_allowlist`:
    - `prom_target("/api/prom/query_range", "query=up&start=1&end=2&step=15")` gives `"http://127.0.0.1:9090/api/v1/query_range?query=up&start=1&end=2&step=15"`
    - `prom_target("/api/prom/admin/tsdb/delete_series", "")` gives `None`
    - `prom_target("/api/prom/../admin", "")` gives `None`
  - `test_static_no_traversal`: a request for `/../server.py` returns 404. Run the real handler on an ephemeral port in a thread.

- [ ] **Step 2: Run** `python3 -m unittest -v` in `web/`. Expected: FAIL.

- [ ] **Step 3: Implement** with `ThreadingHTTPServer` and `SimpleHTTPRequestHandler`, as in `stacks/netwatch/app.py`. Upstream timeout 10 s. If upstream fails, return 502 with `{"error": "..."}`. Only GET is allowed.

- [ ] **Step 4: Run tests.** Expected: PASS.

- [ ] **Step 5: Deploy.** Expected:
  - `curl -s "http://192.168.1.14:8800/api/prom/query?query=up"` returns `"status":"success"`.
  - `/vendor/uPlot.iife.min.js` returns 200.

- [ ] **Step 6: Commit**: "Mission Control: web server and API proxy".

### Task 4: Front-end core (performance view)

**Files:**
- Create: `web/static/{index.html,style.css,lib.js,lib.test.mjs,metrics.js,app.js}`

**Interfaces:**
- `lib.js` (ES module, pure):
  - `RANGES = {"1H":{seconds:3600,step:15}, "24H":{seconds:86400,step:60}, "1W":{seconds:604800,step:600}, "1M":{seconds:2592000,step:1800}, "1Y":{seconds:31536000,step:21600}}`
  - `rateWindow(step: number) -> string`: `max(4*step, 60)` seconds as `"<n>s"`
  - `formatBytes(n) -> string` (B/s, KB/s, MB/s, decimal), `formatBitrate(bits) -> string` (Mb/s, Gb/s), `formatPercent(n)`, `formatTemp(n)` (`47°C`)
  - `summarize(points: (number|null)[]) -> {last, avg, peak, peakIndex}`, which ignores `null` and `NaN`
  - `toSeries(promResult, start, end, step) -> {x: number[], ys: (number|null)[][]}`, which fills the gaps with `null`
- `metrics.js`: `export const METRICS = [{id, label, color, unit, queries: [{name, expr}]}]` with `$w` replaced by `rateWindow(step)`. Exact PromQL:
  - `cpu`: `100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[$w])))`
  - `mem`: `100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)`
  - `temps`:
    - CPU: `node_hwmon_temp_celsius{chip=~".*coretemp.*",sensor="temp1"}`
    - NVMe: `node_hwmon_temp_celsius{chip=~".*nvme.*",sensor="temp1"}`
    - Disk 1 / Disk 2: `smartctl_device_temperature{device="sda",temperature_type="current"}` and the same with `device="sdb"`
    - Check the real label values on the NAS before relying on them.
  - `diskio`: read `sum(rate(node_disk_read_bytes_total{device=~"sda|sdb|nvme0n1"}[$w]))` and write (same with `written`)
  - `net`: in `rate(node_network_receive_bytes_total{device="eth0"}[$w])` and out (`transmit`)
- `app.js` state: `{metric: "cpu", range: "24H", open: null}`. The URL hash mirrors it (`#cpu/24H`, `#card=qbittorrent`), so a reload keeps the view.

- [ ] **Step 1: Failing tests** in `lib.test.mjs` (`node --test`):
  - `formatBytes(1_800_000) === "1.8 MB/s"`
  - `formatBitrate(912_000_000) === "912 Mb/s"`
  - `formatBitrate(1_200_000_000) === "1.2 Gb/s"`
  - `summarize([1, null, 3, NaN, 2])` gives `{last: 2, avg: 2, peak: 3, peakIndex: 2}`. The test name: "summary ignores nulls".
  - `summarize([null, null])` gives `{last: null, avg: null, peak: null, peakIndex: -1}`
  - `rateWindow(15) === "60s"`, `rateWindow(21600) === "86400s"`
  - `toSeries` with one series missing the middle sample gives a `null` at that index, and `x.length === (end-start)/step + 1`

- [ ] **Step 2: Run** `node --test stacks/mission-control/web/static/`. Expected: FAIL.

- [ ] **Step 3: Implement `lib.js` and `metrics.js`.** Then run the tests. Expected: PASS.

- [ ] **Step 4: Build the layout.** `index.html` and `style.css`:
  - Desktop: `body` is `height: 100dvh; overflow: hidden`. The grid is `grid-template-columns: 1fr minmax(16rem, 19rem)`. The left column's rows are `auto 1fr auto auto` (header, chart, tiles, disks). The chart cell has `min-height: 0` and the chart resizes to the cell with a `ResizeObserver`.
  - Phone (`max-width: 480px`): one column, `overflow: auto`, and the chart gets a fixed height of `16rem`.
  - Reuse Homepage's `custom.css` tokens and the `html { font-size: clamp(16px, calc(8px + .5vw), 19px) }` scale.
  - The segmented control is 1H–1Y. The metric tiles are a 5-column grid. The disks strip shows 4 items: RAID 1 (md1), Disk 1, Disk 2, NVMe.
  - The hover readout sits in the header's context line: "avg X · peak Y at HH:MM" changes to "HH:MM · value". It is not a floating tooltip, so nothing gets covered.

- [ ] **Step 5: Wire `app.js`.**
  - Fetch with `query_range` for the selected metric and range. Sparklines are always 24H, fetched once per minute. Live values refresh every 15 s.
  - Disks: `query` for `node_md_disks{state="active"}`, `node_md_disks_required`, `smartctl_device_smart_status`, `smartctl_device_temperature`, `smartctl_device_power_on_seconds`, `smartctl_device_attribute{attribute_name=~"Reallocated_Sector_Ct|Current_Pending_Sector",attribute_value_type="raw"}` and `smartctl_device_percentage_used`.
  - Health dots: green if everything is OK; orange if there are any reallocated or pending sectors, NVMe percentage used is above 80, or a drive is above 50 °C; red if the SMART status fails or RAID is degraded. A click opens a small popover with the details.
  - The chart is uPlot, with an area fill from the metric colour at 40% alpha down to 0. The transition on metric or range change is a 200 ms opacity fade.

- [ ] **Step 6: Verify.**
  - Screenshot at 1920×1080 and 1800×1125, using the `scripts/shoot.sh` approach, pointed at `http://192.168.1.14:8800/`.
  - Expected: no scrollbar, the CPU chart with 24 h of data (whatever exists since Task 1), five tiles with sparklines, and the disks strip with real temperatures.
  - Also screenshot at 1366×768 and 400 px.

- [ ] **Step 7: Commit**: "Mission Control: performance view".

### Task 5: Service cards and expansion

**Files:**
- Modify: `web/static/{index.html,style.css,metrics.js,app.js}`

**Interfaces:**
- `metrics.js` adds `export const CARDS = [{id, title, key: {expr, format, sub}, chart: [{name, expr, color}], tiles: [{label, expr, format}]}]` for `qbittorrent`, `adguard`, `speedtest` and `tailscale`, using the collector metrics. Container CPU/RAM tiles use `mc_container_cpu_percent{name="<container>"}`, with containers `qbittorrent-app-1`, `adguardhome`, `speedtest-tracker` and `tailscale`.
- `app.js`: `openCard(id)` and `closeCard()`. State `open` is a card id or `null`, mirrored in the hash.

- [ ] **Step 1: Rail.**
  - Four service cards, then the Connections card. The Connections card fills the remaining rail height and renders a small static globe preview with the live count from `/api/netwatch` `summary.live`.
  - If a card's source has `mc_up == 0` or no data, its key number shows "—" and the sub-line says "unavailable", in secondary grey.

- [ ] **Step 2: Expansion.**
  - An overlay panel sits over the left column, `position: absolute` within the grid. It grows from the clicked card's rect with a FLIP transform animation: a spring-like `cubic-bezier(.2,.9,.25,1)`, 320 ms, interruptible by re-targeting from the current computed transform.
  - The left column dims to `opacity: .25`. The open card is highlighted.
  - ✕ and Esc close it, and so does clicking the same card. Another card swaps the content without collapsing first.
  - With reduced motion, it uses a 150 ms cross-fade.
  - The panel shows: a header (key number large, the sub-line, the container's CPU/RAM in the context line), the range switch, the chart (same component as Task 4), and its tiles.
  - Tailscale shows a device list (name, online dot, last seen) instead of tiles, read from `mc_tailscale_peer_online` and `mc_tailscale_peer_last_seen_seconds`.

- [ ] **Step 3: Verify.**
  - Screenshots with `#card=qbittorrent`, `#card=adguard`, `#card=speedtest` and `#card=tailscale` at 1920×1080. Each shows real data and no scroll.
  - Stop nothing. To check "—", temporarily point `QBT_URL` at a wrong port, recreate the collector, take a screenshot, then restore it.

- [ ] **Step 4: Commit**: "Mission Control: expandable service cards".

### Task 6: Connections globe

**Files:**
- Create: `web/static/globe.js`
- Modify: `app.js` (the `connections` card), `style.css`

**Interfaces:**
- `globe.js` exports `mountGlobe(el: HTMLElement, {interactive: boolean}) -> {update(state), destroy()}`.
- The state is Netwatch's `/api/state` (`items[]` with `geo.lat`/`geo.lon`, `flag[]` and `live`; `summary` with `live`, `internet_24h` and `flagged_24h`). The home point comes from `state.home`.

- [ ] **Step 1: Implement.**
  - globe.gl with a dark polygon globe from `countries-110m.json` (no texture image downloads), atmosphere on, `arcsData` from home to each item with geo.
  - Arc colours: live items `#30D158`, the rest `#0A84FF` at 35% alpha, flagged items `#FF453A` with a pulsing ring at that point.
  - Hovering a point shows ip, city, country and service in the panel header line, not as a floating tooltip.
  - Preview mode: not interactive, slow auto-rotate, low pixel ratio (`renderer.setPixelRatio(1)`).
  - Expanded mode: drag to spin and scroll to zoom. The header shows "N live · N in 24 h · N flagged".
  - Refresh every 5 s while expanded and every 30 s in preview. With reduced motion, there's no auto-rotate.
  - Pause rendering when the tab is hidden (`document.visibilitychange`). The N100 must not spin a GPU loop in a background tab.

- [ ] **Step 2: Verify.**
  - Screenshot `#card=connections` at 1920×1080.
  - Expected: the globe with arcs. The flagged count matches `curl -s 192.168.1.14:8790/api/state` `summary.flagged_24h`.
  - Headless Firefox may lack WebGL. If the screenshot is blank, verify in the user's Brave and ask them for a screenshot.

- [ ] **Step 3: Commit**: "Mission Control: connections globe".

### Task 7: Integration and docs

**Files:**
- Modify: `stacks/homepage/config/bookmarks.yaml` (Dock: `Mission Control`, icon `mdi-monitor-dashboard`, href `http://192.168.1.14:8800`)
- Modify: `README.md`: services table, a new "Mission Control" section (what, architecture table, metrics, how to add a card), the security note (SMART caps, every port bound to 127.0.0.1 except 8800, dockerproxy on 127.0.0.1:2375), and the changelog
- Modify: `stacks/netwatch/app.py` `LOCAL_SERVICES` (add `8800: "Mission Control"`)

- [ ] **Step 1: Apply.** Copy the bookmarks to the NAS. Rebuild Netwatch. Add an Uptime Kuma HTTP monitor `http://192.168.1.14:8800` through its UI, or ask the user to.

- [ ] **Step 2: Check load.**
  - Run: `ssh <user>@192.168.1.14 'docker stats --no-stream | grep -E "prometheus|exporter|mc-|collector|web"; du -sh /volume1/docker/mission-control/data'`
  - Expected: total RAM under 500 MB.

- [ ] **Step 3: Final screenshots.**
  - Homepage with the new dock icon. Mission Control at 1920×1080, 1800×1125, 1366×768 and 400 px.
  - Run `scripts/sync-from-nas.sh`. Its secret check must pass.

- [ ] **Step 4: Commit**: "Mission Control: dock link, docs". Push only after the user's OK.
