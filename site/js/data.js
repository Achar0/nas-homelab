// Topology of the homelab, taken from README.md (the source of truth).
// Public repo: no tailnet name, no personal hosts. Keep it in sync with the README.
//
// Node fields:
//   col, row  grid cell (see groups); lines are routed through the gaps between cells
//   needs     requirements; each is an id or an array of ids (any one is enough).
//             If one is not met, the node is down.
//   soft      ids that only degrade the node when they are down
//   facts     key/value rows for the detail panel
//   notes     bullets for the detail panel
//   onFail    what the user notices when this node fails

window.HOMELAB = {
  reviewed: "2026-11-16",
  repo: "https://github.com/Achar0/nas-homelab",

  // Sections, by grid columns/rows. Each is drawn as its own panel; part: "nas" sits under the NAS title.
  groups: [
    { id: "outside", label: "Outside", c0: 0, c1: 0, r0: 0, r1: 2 },
    { id: "lan", label: "Home network", c0: 1, c1: 1, r0: 1, r1: 3 },
    { id: "edge", label: "Edge", c0: 2, c1: 2, r0: 0, r1: 2, part: "nas" },
    { id: "apps", label: "Own apps", c0: 3, c1: 3, r0: 0, r1: 3, part: "nas" },
    { id: "media", label: "Media", c0: 4, c1: 4, r0: 0, r1: 2, part: "nas" },
    { id: "ops", label: "Monitoring & ops", c0: 5, c1: 5, r0: 0, r1: 4, part: "nas" },
    { id: "storage", label: "Storage · /volume1 btrfs", c0: 2, c1: 5, r0: 5, r1: 6, part: "nas" },
  ],
  nas: { title: "NAS", note: "UGREEN DXP4800 · 192.168.1.14" },


  nodes: [
    // Outside the NAS
    {
      id: "internet", label: "Internet", sub: "ISP uplink", icon: "globe", col: 0, row: 2,
      needs: ["router"],
      facts: { "Port forwards": "none (router ignores UPnP)", "Inbound": "only through Tailscale" },
      notes: ["Upstream DNS for AdGuard, torrent peers, Mikan RSS, GeoIP lists and ntfy push all go out here."],
      onFail: "No new episodes, no upstream DNS, no push alerts. Everything local keeps working.",
    },
    {
      id: "remote", label: "Away from home", sub: "phone on Tailscale", icon: "phone", col: 0, row: 0,
      needs: ["internet", "tailscale"], soft: ["caddy"],
      facts: { "Reaches": "192.168.1.x through the subnet route", "Name": "<nas-name>.<tailnet>.ts.net" },
      notes: ["MagicDNS gives the tailnet address, so HTTPS and passkeys work from anywhere."],
      onFail: "Only this device is affected.",
    },
    {
      id: "router", label: "ISP router", sub: "192.168.1.1 · Wi-Fi 6", icon: "router", col: 1, row: 2,
      needs: [],
      facts: { "LAN": "192.168.1.0/24", "DHCP": "reserves 192.168.1.14 for the NAS", "DNS handed out": "192.168.1.14 (AdGuard)" },
      notes: ["UPnP requests get no answer (checked with scripts/upnp_list.py), so nothing is opened automatically."],
      onFail: "The whole LAN is cut off: no Wi-Fi, no internet, no NAS from phones or TV.",
    },
    {
      id: "clients", label: "Phones & laptop", sub: "LAN, Wi-Fi", icon: "laptop", col: 1, row: 1,
      needs: ["router"], soft: ["adguard", "caddy"],
      facts: { "DNS": "AdGuard (via DHCP)", "Admin pages": "HTTPS :3443 / :8843 / :8793" },
      notes: ["Secure DNS or iCloud Private Relay bypass AdGuard; then the Tailscale name doesn't resolve to the LAN address at home."],
      onFail: "Only this device is affected.",
    },
    {
      id: "tv", label: "Fire TV", sub: "idle page + IPTV", icon: "tv", col: 1, row: 3,
      needs: ["router"], soft: ["home", "theater"],
      facts: { "Idle page": "http://192.168.1.14:3001/tv", "Playlist": "/iptv.m3u" },
      notes: ["Stays on plain HTTP on purpose: /tv, /api/public/tv, /api/news and /iptv.m3u are the only GET paths :3001 still serves."],
      onFail: "Only the TV is affected.",
    },

    // Edge
    {
      id: "tailscale", label: "Tailscale", sub: "node nas · subnet route", icon: "tunnel", col: 2, row: 0,
      needs: ["nas"], soft: ["internet"],
      facts: { "Image": "tailscale/tailscale, host network", "Route": "192.168.1.0/24 (approved once)", "Key expiry": "disabled" },
      notes: [
        "Entrypoint runs tailscaled directly: containerboot gave up after 60 s and looped.",
        "State in state/; if lost, re-run tailscale up with the same flags.",
        "Also issues the HTTPS certificate Caddy uses.",
      ],
      onFail: "No remote access and no new certificates. At home everything keeps working.",
    },
    {
      id: "caddy", label: "Caddy", sub: "HTTPS · Tailscale cert", icon: "lock", col: 2, row: 1,
      needs: ["nas"], soft: ["tailscale"],
      facts: { "Ports": ":3443 Home · :8843 Mission Control · :8793 Netwatch · :9943 UGOS", "Certificate": "Tailscale CA via tailscaled socket", "Redirects": "disabled; apps redirect themselves" },
      notes: [
        "Proxies to the apps on 127.0.0.1 and always adds X-Forwarded-*, so proxied requests never count as internal loopback.",
        "UGOS (:9943) goes to its own 127.0.0.1:9443 with tls_insecure_skip_verify; the browser only sees the Tailscale certificate.",
      ],
      onFail: "Admin pages unreachable over HTTPS (plain HTTP no longer serves them). Uptime Kuma alerts. Emergency fallback: blank NAS_TS_NAME.",
    },
    {
      id: "adguard", label: "AdGuard Home", sub: ":53 · :8080", icon: "shield", col: 2, row: 2,
      needs: ["nas"], soft: ["internet"],
      facts: { "Binds": "192.168.1.14:53 only (dnsmasq clash)", "Lists": "AdGuard DNS, HaGeZi Pro + TIF, anti-AD", "RAM": "~600 MB" },
      notes: [
        "Rewrite <nas-name>.<tailnet>.ts.net → 192.168.1.14 so passkeys work at home without Tailscale.",
        "Can't remove first-party banners; use Brave Shields for those.",
      ],
      onFail: "Devices lose DNS until they fall back; the HTTPS name stops resolving at home.",
    },

    // Own apps
    {
      id: "home", label: "Home", sub: ":3001 · guest / admin / TV", icon: "home", col: 3, row: 0,
      needs: ["nas", "volume"], soft: ["proxy", "glances", "netwatch", "speedtest", "qbit"],
      facts: { "Guest": "status, news, downloads", "Admin": "/admin/ · passkeys or password", "TV": "/tv · /iptv.m3u" },
      notes: ["Owner's page: attention cards with urgent takeover + ntfy push, news, arrivals, IPTV lists, dock."],
      onFail: "Guests and the TV idle page go blank. Uptime Kuma's Homepage monitor fires.",
    },
    {
      id: "netwatch", label: "Netwatch", sub: ":8790 → :8793", icon: "radar", col: 3, row: 1,
      needs: ["nas"], soft: ["internet"],
      facts: { "Shows": "connection map, attacker flags", "Alerts": "ntfy on attacker / unexpected inbound", "Login": "admin session" },
      notes: ["Pulls GeoIP and blocklists from the internet."],
      onFail: "No connection map and no attacker alerts.",
    },
    {
      id: "mission", label: "Mission Control", sub: ":8800 → :8843", icon: "chart", col: 3, row: 2,
      needs: ["nas", "prometheus"], soft: ["netwatch"],
      facts: { "History": "1 year", "Shows": "performance, disks (SMART), services", "Login": "admin session" },
      notes: ["Capture with ?static for screenshots: headless Firefox has no animations or WebGL."],
      onFail: "No performance history view. Metrics keep being collected by Prometheus.",
    },
    {
      id: "kuma", label: "Uptime Kuma", sub: ":3002 · v2", icon: "pulse", col: 3, row: 3,
      needs: ["nas"], soft: ["internet"],
      facts: { "Alerts": "private ntfy.sh topic", "Theater monitor": "Ignore TLS errors (self-signed :9443)" },
      notes: ["Pre-upgrade 1.23.17 data kept in data.bak-1.23.17."],
      onFail: "Outages go unnoticed until you look.",
    },

    // Media
    {
      id: "qbit", label: "qBittorrent", sub: ":8888 · peers :6888", icon: "download", col: 4, row: 0,
      needs: ["nas", "volume"], soft: ["internet"],
      facts: { "Source": "UGREEN app (@appstore), root-owned", "Seeding": "forever, all limits off", "Extra mount": "/media (re-check after app updates)" },
      notes: ["Locks an IP out after 5 failed logins; restarting the app clears it.", "Move finished torrents with Set location so seeding continues."],
      onFail: "Downloads and seeding stop; AutoBangumi can't hand off new episodes.",
    },
    {
      id: "autobangumi", label: "AutoBangumi", sub: ":7892", icon: "rss", col: 4, row: 1,
      needs: ["nas", "qbit"], soft: ["internet"],
      facts: { "Feeds": "Mikan RSS, fixed release group", "Save path": "/media/番剧", "Rename": "pn, through qBittorrent" },
      notes: ["Use the episode offset for groups that number across seasons."],
      onFail: "New episodes stop arriving automatically.",
    },
    {
      id: "theater", label: "UGOS Theater", sub: "影视中心 · :9943", icon: "film", col: 4, row: 2,
      needs: ["nas", "volume"], soft: ["caddy"],
      facts: { "Libraries": "电影 · 电视剧 · 番剧", "Rescan": "live on file moves", "Pinning": "tvshow.nfo with TMDB id", "Fallback": "https://192.168.1.14:9443 (self-signed)" },
      notes: ["Takes the show title from file names: rename to Season NN/<Show> SNNEMM.ext through qBittorrent."],
      onFail: "Media library unavailable on TV and phones.",
    },

    // Monitoring & ops
    {
      id: "prometheus", label: "Prometheus", sub: "127.0.0.1 only", icon: "db", col: 5, row: 0,
      needs: ["nas", "volume"], soft: ["proxy", "adguard", "qbit", "speedtest"],
      facts: { "Retention": "1 year", "Scrapes": "docker proxy, AdGuard, qBittorrent, Speedtest, SMART", "Admin API": "never exposed" },
      notes: ["mc-smartctl-exporter gets exactly /dev/sda, /dev/sdb, /dev/nvme0 with SYS_RAWIO (not privileged)."],
      onFail: "Gap in performance history; Mission Control goes empty.",
    },
    {
      id: "proxy", label: "Socket proxy", sub: "Docker, read-only · :2375", icon: "box", col: 5, row: 1,
      needs: ["nas"],
      facts: { "Clients": "Home, Mission Control", "Access": "read-only, 127.0.0.1" },
      notes: ["Only Dockge gets the real socket (root-equivalent)."],
      onFail: "Home and Mission Control lose container status.",
    },
    {
      id: "speedtest", label: "Speedtest Tracker", sub: ":8765 · every 6 h", icon: "gauge", col: 5, row: 2,
      needs: ["nas"], soft: ["internet"],
      facts: { "History": "1 year", "Token": "results:read, in mission-control/.env" },
      notes: ["A token dies with the user that owns it; recreate it with a small PHP script (no artisan tinker)."],
      onFail: "Speed history stops.",
    },
    {
      id: "glances", label: "Glances", sub: ":61208", icon: "cpu", col: 5, row: 3,
      needs: ["nas"],
      facts: { "Login": "own password (user glances)", "Open": "/api/4/status, /docs only" },
      notes: [],
      onFail: "Live CPU/RAM numbers disappear from Home.",
    },
    {
      id: "dockge", label: "Dockge", sub: ":5001", icon: "layers", col: 5, row: 4,
      needs: ["nas"],
      facts: { "Manages": "/volume1/docker stacks", "Socket": "full access, strong login" },
      notes: ["Doesn't manage the @appstore apps."],
      onFail: "No web UI for stacks; use SSH + docker compose.",
    },

    // The box itself and its storage
    {
      id: "nas", label: "UGOS Pro", sub: "N100 · 8 GB · Docker 29.6", icon: "server", col: 2, row: 5,
      needs: [],
      facts: { "OS": "Debian 12 based, kernel 6.18", "Compose": "v5.1", "Stacks": "/volume1/docker/<stack>", "Firewall": "LAN + Docker + tailnet 100.64/10" },
      notes: ["SSH sometimes switches itself off; re-enable in Control Panel → Terminal.", "Container names follow name-port, e.g. autobangumi-7892."],
      onFail: "Every service on the NAS is down.",
    },
    {
      id: "volume", label: "volume1", sub: "btrfs · RAID 1 · ~3.6 TB", icon: "drive", col: 3, row: 5,
      needs: ["nas", ["hdd1", "hdd2"]], soft: ["hdd1", "hdd2"],
      facts: { "Snapshots": "UGOS btrfs, read-only", "Integrity": "scripts/nas-check.sh monthly", "Off-site": "none" },
      notes: ["Last check 2026-11-13: 897 GiB scrubbed in 58 min, no errors.", "Not covered: theft, fire, an attacker with UGOS admin."],
      onFail: "All data and every stack that stores state is gone until restored.",
    },
    {
      id: "hdd1", label: "Disk A", sub: "IronWolf 4 TB · RAID 1", icon: "disk", col: 4, row: 5,
      needs: [],
      facts: { "Role": "mirror half", "SMART": "Mission Control" },
      notes: [],
      onFail: "RAID 1 runs degraded on the other disk. No data loss; replace soon.",
    },
    {
      id: "hdd2", label: "Disk B", sub: "IronWolf 4 TB · RAID 1", icon: "disk", col: 4, row: 6,
      needs: [],
      facts: { "Role": "mirror half", "SMART": "Mission Control" },
      notes: [],
      onFail: "RAID 1 runs degraded on the other disk. No data loss; replace soon.",
    },
    {
      id: "nvme", label: "Crucial NVMe", sub: "500 GB LVM cache", icon: "chip", col: 5, row: 5,
      needs: [],
      facts: { "Mode": "writethrough", "Note": "UGOS scrub scheduler refuses the pool because of it" },
      notes: ["Writethrough: every write also lands on the disks first."],
      onFail: "Slower reads only. Writethrough means no data is lost.",
    },
  ],

  // quiet: secondary links. Hidden in the "All" view; shown in their own view (Network/Services/Storage),
  // when one of their nodes is hovered or selected, or when a flow uses them.
  // Link types: wan, lan, tunnel, dns, https, app, metrics, docker, storage, push
  links: [
    { a: "router", b: "internet", type: "wan" },
    { a: "router", b: "clients", type: "lan", label: "Wi-Fi" },
    { a: "router", b: "tv", type: "lan", label: "Wi-Fi" },
    { a: "router", b: "nas", type: "lan", label: "eth0" },
    { a: "remote", b: "internet", type: "wan" },
    { a: "remote", b: "tailscale", type: "tunnel", label: "WireGuard" },
    { a: "tailscale", b: "internet", type: "tunnel", quiet: true },

    { a: "clients", b: "adguard", type: "dns", label: "DNS :53" },
    { a: "tv", b: "adguard", type: "dns" },
    { a: "adguard", b: "internet", type: "dns", quiet: true, label: "upstream" },

    { a: "clients", b: "caddy", type: "https", label: "HTTPS" },
    { a: "tailscale", b: "caddy", type: "https" },
    { a: "caddy", b: "home", type: "https" },
    { a: "caddy", b: "netwatch", type: "https" },
    { a: "caddy", b: "mission", type: "https" },
    { a: "caddy", b: "theater", type: "https", quiet: true },
    { a: "tv", b: "home", type: "app", label: "HTTP /tv", quiet: true },

    { a: "home", b: "glances", type: "app", quiet: true },
    { a: "home", b: "netwatch", type: "app" },
    { a: "home", b: "speedtest", type: "app", quiet: true },
    { a: "home", b: "qbit", type: "app" },
    { a: "home", b: "proxy", type: "docker", quiet: true },
    { a: "mission", b: "prometheus", type: "metrics" },
    { a: "mission", b: "netwatch", type: "app" },
    { a: "prometheus", b: "proxy", type: "metrics", quiet: true },
    { a: "prometheus", b: "speedtest", type: "metrics", quiet: true },
    { a: "prometheus", b: "qbit", type: "metrics", quiet: true },
    { a: "prometheus", b: "adguard", type: "metrics", quiet: true },
    { a: "dockge", b: "nas", type: "docker", quiet: true, label: "docker.sock" },

    { a: "autobangumi", b: "qbit", type: "app", label: "add torrent" },
    { a: "autobangumi", b: "internet", type: "wan", quiet: true, label: "Mikan RSS" },
    { a: "qbit", b: "internet", type: "wan", quiet: true, label: "peers" },
    { a: "qbit", b: "volume", type: "storage", label: "/media" },
    { a: "theater", b: "volume", type: "storage" },
    { a: "tv", b: "theater", type: "app", quiet: true },
    { a: "kuma", b: "home", type: "app" },
    { a: "kuma", b: "internet", type: "push", quiet: true, label: "ntfy" },
    { a: "netwatch", b: "internet", type: "push", quiet: true },

    { a: "nas", b: "volume", type: "storage" },
    { a: "volume", b: "hdd1", type: "storage" },
    { a: "volume", b: "hdd2", type: "storage" },
    { a: "volume", b: "nvme", type: "storage", label: "cache" },
    { a: "prometheus", b: "volume", type: "storage", quiet: true },
  ],

  linkTypes: {
    wan: { label: "WAN / internet", layer: "network" },
    lan: { label: "LAN · Wi-Fi / Ethernet", layer: "network" },
    tunnel: { label: "Tailscale tunnel", layer: "network" },
    dns: { label: "DNS", layer: "network" },
    https: { label: "HTTPS via Caddy", layer: "network" },
    app: { label: "App to app (HTTP)", layer: "services" },
    metrics: { label: "Metrics scrape", layer: "services" },
    docker: { label: "Docker socket", layer: "services" },
    push: { label: "Push alert (ntfy)", layer: "services" },
    storage: { label: "Storage", layer: "storage" },
  },

  // Guided flows: a path of node ids, with one caption per hop.
  flows: [
    {
      id: "guest", title: "Opening the Home page at home",
      path: ["clients", "adguard", "clients", "caddy", "home", "glances"],
      steps: [
        "A phone on the home Wi-Fi asks for <nas-name>.<tailnet>.ts.net.",
        "AdGuard's rewrite answers 192.168.1.14, so the request stays on the LAN.",
        "The phone opens https://…:3443.",
        "Caddy terminates TLS with the Tailscale certificate and proxies to Home on 127.0.0.1:3001.",
        "Home fills in live numbers from Glances, Netwatch and Speedtest.",
      ],
    },
    {
      id: "remote", title: "Checking Mission Control from outside",
      path: ["remote", "internet", "tailscale", "caddy", "mission", "prometheus"],
      steps: [
        "Away from home, the phone has Tailscale on.",
        "WireGuard goes out over the internet; no port is opened on the router.",
        "The tunnel ends at node nas, whose firewall allows 100.64.0.0/10.",
        "Caddy on :8843 terminates HTTPS and forwards; Mission Control asks for the admin session (passkey).",
        "Mission Control reads one year of history from Prometheus.",
      ],
    },
    {
      id: "episode", title: "A new episode arrives",
      path: ["internet", "autobangumi", "qbit", "volume", "theater", "tv"],
      steps: [
        "Mikan publishes the episode in the show's RSS feed.",
        "AutoBangumi matches the release group and hands the torrent to qBittorrent.",
        "qBittorrent downloads into /media/番剧/<Show>/Season N and keeps seeding forever.",
        "The Theater rescans live when the file appears.",
        "It's on the Fire TV, renamed so the Theater matches the right show.",
      ],
    },
    {
      id: "alert", title: "Something goes down",
      path: ["home", "kuma", "internet", "remote"],
      steps: [
        "Home stops answering on :3001.",
        "Uptime Kuma's monitor fails and posts to the private ntfy.sh topic.",
        "ntfy pushes the alert to the phone, wherever it is.",
      ],
    },
  ],
};
