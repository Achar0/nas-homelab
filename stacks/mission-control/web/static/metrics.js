// What the page shows: each performance metric and its Prometheus queries.
// $w is replaced with the rate window that matches the chart's step (see lib.rateWindow).
import { formatBytes, formatPercent, formatTemp } from "./lib.js";

// md1 = hard-drive RAID 1 volume, md2 = NVMe volume: counting the volumes (not sda+sdb) counts
// each mirrored write once
const DISKS = 'device=~"md1|md2"';

export const METRICS = [
  {
    id: "cpu", label: "Processor", color: "#0A84FF", format: formatPercent, max: 100,
    queries: [{ name: "Processor", expr: '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[$w])))' }],
  },
  {
    id: "mem", label: "Memory", color: "#BF5AF2", format: formatPercent, max: 100,
    queries: [{ name: "Memory", expr: "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)" }],
  },
  {
    id: "temps", label: "Temperatures", color: "#FF9F0A", format: formatTemp,
    queries: [
      { name: "CPU", expr: 'node_hwmon_temp_celsius{chip=~".*coretemp.*",sensor="temp1"}' },
      { name: "NVMe", expr: 'node_hwmon_temp_celsius{chip=~".*nvme.*",sensor="temp1"}', color: "#FFD60A" },
      { name: "Disk 1", expr: 'smartctl_device_temperature{device="sda",temperature_type="current"}', color: "#FF6482" },
      { name: "Disk 2", expr: 'smartctl_device_temperature{device="sdb",temperature_type="current"}', color: "#AC8E68" },
    ],
  },
  {
    id: "diskio", label: "Disk I/O", color: "#64D2FF", format: formatBytes,
    queries: [
      { name: "Read", expr: `sum(rate(node_disk_read_bytes_total{${DISKS}}[$w]))` },
      { name: "Write", expr: `sum(rate(node_disk_written_bytes_total{${DISKS}}[$w]))`, color: "#5E5CE6" },
    ],
  },
  {
    id: "net", label: "Network", color: "#30D158", format: formatBytes,
    queries: [
      { name: "In", expr: 'rate(node_network_receive_bytes_total{device="eth0"}[$w])' },
      { name: "Out", expr: 'rate(node_network_transmit_bytes_total{device="eth0"}[$w])', color: "#66D4CF" },
    ],
  },
];

// Hosted services in the rail. key = the one number on the card; chart/tiles = the expanded view.
import { formatBitrate, formatSize, formatPlain, formatMs, formatCount } from "./lib.js";

// Links use the address the page was opened with (LAN IP, Tailscale IP or MagicDNS name all work)
const at = (port, scheme = "http") => `${scheme}://${location.hostname}:${port}`;

// Same apps as Homepage's dock, plus Homepage itself. mono = single-colour icon (tinted by CSS)
export const DOCK = [
  { name: "Home", icon: "mdi-home.svg", mono: true, href: at(3001) },
  { name: "AdGuard", icon: "adguard-home.svg", href: at(8080) },
  { name: "qBittorrent", icon: "qbittorrent.svg", href: at(8888) },
  { name: "AutoBangumi", icon: "mdi-television-classic.svg", mono: true, href: at(7892) },
  { name: "Speedtest", icon: "speedtest-tracker.svg", href: at(8765) },
  { name: "Uptime Kuma", icon: "uptime-kuma.svg", href: at(3002) },
  { name: "Dockge", icon: "dockge.svg", href: at(5001) },
  { name: "Netwatch", icon: "mdi-earth.svg", mono: true, href: at(8790) },
  { name: "Glances", icon: "glances.svg", href: at(61208) },
  { name: "UGOS", icon: "mdi-nas.svg", mono: true, href: at(9443, "https") },
];

const cpu = (c) => ({ label: "CPU", expr: `mc_container_cpu_percent{name="${c}"}`, format: formatPercent });
const ram = (c) => ({ label: "Memory", expr: `mc_container_memory_bytes{name="${c}"}`, format: formatSize });

export const CARDS = [
  {
    id: "qbittorrent", href: at(8888), title: "qBittorrent", source: "qbittorrent", color: "#30D158",
    key: { expr: "mc_qbt_upload_bytes_per_second", format: formatBytes, label: "upload" },
    sub: { expr: "mc_qbt_seeding", text: (v) => `upload · ${formatCount(v)} seeding` },
    chart: [
      { name: "Upload", expr: "mc_qbt_upload_bytes_per_second", color: "#30D158" },
      { name: "Download", expr: "mc_qbt_download_bytes_per_second", color: "#0A84FF" },
    ],
    chartFormat: formatBytes,
    tiles: [
      { label: "Seeding", expr: "mc_qbt_seeding", format: formatCount },
      { label: "Uploaded (session)", expr: "mc_qbt_uploaded_session_bytes", format: formatSize },
      { label: "Ratio", expr: "mc_qbt_ratio", format: formatPlain },
      cpu("qbittorrent-app-1"), ram("qbittorrent-app-1"),
    ],
  },
  {
    id: "adguard", href: at(8080), title: "AdGuard", source: "adguard", color: "#FF453A",
    key: { expr: "100 * mc_adguard_blocked_24h / mc_adguard_queries_24h", format: formatPercent, label: "blocked" },
    sub: { expr: "mc_adguard_queries_24h", text: (v) => `blocked · ${formatCount(v)} queries in 24 h` },
    chart: [
      { name: "Queries", expr: "mc_adguard_queries_24h", color: "#0A84FF" },
      { name: "Blocked", expr: "mc_adguard_blocked_24h", color: "#FF453A" },
    ],
    chartFormat: formatCount,
    chartNote: "rolling 24 h totals",
    tiles: [
      { label: "Blocked", expr: "100 * mc_adguard_blocked_24h / mc_adguard_queries_24h", format: formatPercent },
      { label: "Queries · 24 h", expr: "mc_adguard_queries_24h", format: formatCount },
      { label: "Latency", expr: "1000 * mc_adguard_latency_seconds", format: formatMs },
      { label: "Top blocked", expr: "mc_adguard_top_blocked", labelOf: "domain" },
      cpu("adguardhome"), ram("adguardhome"),
    ],
  },
  {
    id: "speedtest", href: at(8765), title: "Speedtest", source: "speedtest", color: "#0A84FF",
    key: { expr: "mc_speedtest_download_bits_per_second", format: formatBitrate, label: "download" },
    sub: { expr: "mc_speedtest_last_timestamp_seconds", ago: true, text: (ago) => `download · ${ago}` },
    chart: [
      { name: "Download", expr: "mc_speedtest_download_bits_per_second", color: "#0A84FF" },
      { name: "Upload", expr: "mc_speedtest_upload_bits_per_second", color: "#BF5AF2" },
    ],
    chartFormat: formatBitrate,
    tiles: [
      { label: "Download", expr: "mc_speedtest_download_bits_per_second", format: formatBitrate },
      { label: "Upload", expr: "mc_speedtest_upload_bits_per_second", format: formatBitrate },
      { label: "Ping", expr: "mc_speedtest_ping_ms", format: formatMs },
      cpu("speedtest-tracker"), ram("speedtest-tracker"),
    ],
  },
  {
    id: "tailscale", href: "https://login.tailscale.com/admin/machines", title: "Tailscale", source: "tailscale", color: "#64D2FF",
    key: { expr: "mc_tailscale_peers_online", format: formatCount, label: "online" },
    sub: { text: (v) => "devices online" },
    chart: [{ name: "Devices online", expr: "mc_tailscale_peers_online", color: "#64D2FF" }],
    chartFormat: formatCount,
    devices: true,
    tiles: [cpu("tailscale"), ram("tailscale")],
  },
];
