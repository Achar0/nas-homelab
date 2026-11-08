"""What family and guests see on the public page (pure, no I/O).

Built here on the server so nothing technical can leak: no IP addresses, container or drive names,
alert text or raw torrent names. Security events (Netwatch) never reach this page.
"""
import attention
import weather

STALE_S = 300
REQUIRED_SOURCES = ("kuma", "prom", "restarts")   # all must be readable to claim "all online"

OK = {"state": "ok", "title": "Everything's running", "detail": "All services are online"}
UNKNOWN = {"state": "unknown", "title": "Status unavailable", "detail": ""}
STORAGE = "Storage needs attention"
BROKEN = "Something isn't working right now"
SLOW = "Internet is slow right now"

# Uptime Kuma monitor name (lowercase, matched as a substring; first match wins) -> plain name
PLAIN_NAMES = (("adguard", "Ad blocking"), ("qbittorrent", "Downloading"), ("autobangumi", "Episode tracking"),
               ("speedtest", "Speed test"), ("mission control", "Monitoring"), ("netwatch", "Monitoring"),
               ("tailscale", "Remote access"), ("theater", "The media library"), ("home", "The home page"))


def _warn(title, detail=""):
    return {"state": "warn", "title": title, "detail": detail}


DEMO = {   # ?demo=<key>: previews only, never stored or pushed
    "down": _warn("Ad blocking is down"),
    "storage": _warn(STORAGE),
    "restart": _warn(BROKEN),
    "slow": _warn(SLOW),
    "many": _warn(STORAGE, "and 2 more"),
    "unknown": UNKNOWN,
}


def _plain_name(monitor):
    low = monitor.lower()
    return next((plain for key, plain in PLAIN_NAMES if key in low), "A service") + " is down"


def _rank(cid):
    """(severity, line) for one condition; lower is more serious."""
    kind, _, rest = cid.partition(":")
    if kind in ("raid", "smart"):
        return 0, STORAGE
    if kind == "kuma-down":
        return 1, _plain_name(rest)
    if kind == "restarts":
        return 2, BROKEN
    if kind in ("hot", "space"):
        return 3, STORAGE
    return 4, SLOW   # speed


def _source_unreadable(inputs):
    if any(inputs.get(k) is None for k in REQUIRED_SOURCES) or not inputs["kuma"]:
        return True
    # Prometheus can answer while an exporter is down: empty readings are not good news
    prom = inputs["prom"]
    return (any(prom.get(k) is None for k in ("free_ratio", "md_active", "speed_last"))
            or not prom.get("smart_status") or not prom.get("drive_temp"))


def status(inputs, now, updated, rules=attention.DEFAULT_RULES):
    if inputs is None or now - updated > STALE_S:
        return UNKNOWN
    readable = {k: inputs.get(k) for k in REQUIRED_SOURCES}   # no Netwatch, no episode rule
    active, _ = attention.conditions(readable, now, rules)
    if active:
        ranked = sorted(_rank(cid) for cid in active)
        more = len(ranked) - 1
        return _warn(ranked[0][1], f"and {more} more" if more else "")
    return UNKNOWN if _source_unreadable(inputs) else OK


def downloads(data):
    """Recognised episodes by name; everything else only as a count."""
    def known(items):
        return [{k: v for k, v in x.items() if k != "known"} for x in items if x.get("known")]
    arrived, downloading = data.get("arrived", []), data.get("downloading", [])
    other = sum(1 for x in arrived + downloading if not x.get("known"))
    return {"arrived": known(arrived), "downloading": known(downloading), "other": other}


def summary(inputs, arrivals_data, now, updated, rules=attention.DEFAULT_RULES):
    prom = (inputs or {}).get("prom") or {}
    return {"status": status(inputs, now, updated, rules), "internet_bps": prom.get("speed_last"),
            "free_bytes": prom.get("free_bytes"), "downloads": downloads(arrivals_data)}


# ---------- TV page (/tv): Chinese first, a small English line underneath ----------

TV_EPISODES = 3
ZH_TITLES = {STORAGE: "存储需要检查", BROKEN: "有些服务出了问题", SLOW: "网络有点慢"}
ZH_NAMES = {"Ad blocking": "广告拦截", "Downloading": "下载", "Episode tracking": "追剧更新", "Speed test": "测速",
            "Monitoring": "监控", "Remote access": "远程访问", "The media library": "影音库", "The home page": "主页",
            "A service": "某项服务"}


def tv_line(title):
    """One guest status title in both languages; the only place with this Chinese copy."""
    name = title.removesuffix(" is down")
    zh = ZH_NAMES[name] + "暂时不可用" if name in ZH_NAMES else ZH_TITLES.get(title, title)
    return {"zh": zh, "en": title}


def tv_status(line):
    """The status line only appears when something is wrong: `ok` and `unknown` show nothing."""
    return tv_line(line["title"]) if line["state"] == "warn" else None


def tv(inputs, arrivals_data, weather_data, now, updated, rules=attention.DEFAULT_RULES):
    d = downloads(arrivals_data)
    arrived = [{"show": a["show"], "ep": a["ep"], "at": a["at"]} for a in d["arrived"]]
    active = [{"show": a["show"], "ep": a["ep"], "at": None} for a in d["downloading"]]
    return {"status": tv_status(status(inputs, now, updated, rules)), "weather": weather.fresh(weather_data, now),
            "episodes": (arrived + active)[:TV_EPISODES]}
