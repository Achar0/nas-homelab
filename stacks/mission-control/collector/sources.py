"""Turn each service's API response into Prometheus metrics.

Pure functions only (no network): collector.py fetches, these parse.
A metric is (name, labels, value).
"""
import datetime as dt

SEEDING_STATES = {"uploading", "stalledUP", "queuedUP", "forcedUP"}


def _ts(iso):
    """ISO-8601 time ('...Z') -> unix seconds; Go's zero time -> None."""
    if not iso or iso.startswith("0001-"):
        return None
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def parse_docker(containers, stats):
    """containers: /containers/json; stats: {container id: /containers/<id>/stats}."""
    out = []
    for c in containers:
        s = stats.get(c["Id"])
        if not s:
            continue
        name = c["Names"][0].lstrip("/")
        cpu, pre = s["cpu_stats"], s["precpu_stats"]
        cpu_d = cpu["cpu_usage"]["total_usage"] - pre.get("cpu_usage", {}).get("total_usage", 0)
        sys_d = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        # system_cpu_usage counts all cores, so this is already a share of the whole NAS (0-100)
        pct = 100.0 * cpu_d / sys_d if sys_d > 0 and cpu_d > 0 else 0.0
        mem = s.get("memory_stats", {})
        used = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", 0)
        out += [("mc_container_cpu_percent", {"name": name}, pct),
                ("mc_container_memory_bytes", {"name": name}, max(used, 0))]
    return out


def parse_qbt(transfer, torrents, maindata):
    state = maindata.get("server_state", {})
    return [
        ("mc_qbt_upload_bytes_per_second", {}, transfer["up_info_speed"]),
        ("mc_qbt_download_bytes_per_second", {}, transfer["dl_info_speed"]),
        ("mc_qbt_seeding", {}, sum(t["state"] in SEEDING_STATES for t in torrents)),
        ("mc_qbt_uploaded_session_bytes", {}, transfer["up_info_data"]),
        ("mc_qbt_ratio", {}, float(state.get("global_ratio", 0) or 0)),
    ]


def parse_adguard(stats):
    out = [
        ("mc_adguard_queries_24h", {}, stats["num_dns_queries"]),
        ("mc_adguard_blocked_24h", {}, stats["num_blocked_filtering"]),
        ("mc_adguard_latency_seconds", {}, stats["avg_processing_time"]),
    ]
    top = stats.get("top_blocked_domains") or []
    if top:
        out.append(("mc_adguard_top_blocked", {"domain": next(iter(top[0]))}, 1))
    return out


def parse_speedtest(latest):
    d = latest["data"]
    # Speedtest Tracker gives download/upload in bytes/s and *_bits in bits/s: use the bits fields
    out = [
        ("mc_speedtest_download_bits_per_second", {}, d["download_bits"]),
        ("mc_speedtest_upload_bits_per_second", {}, d["upload_bits"]),
        ("mc_speedtest_ping_ms", {}, d["ping"]),
    ]
    ts = _ts((d.get("data") or {}).get("timestamp"))
    if ts:
        out.append(("mc_speedtest_last_timestamp_seconds", {}, ts))
    return out


def parse_tailscale(status, now):
    devices = [status["Self"]] + list((status.get("Peer") or {}).values())
    out = [("mc_tailscale_peers_online", {}, sum(bool(d.get("Online")) for d in devices))]
    for d in devices:
        name = d.get("HostName", "?")
        online = bool(d.get("Online"))
        out.append(("mc_tailscale_peer_online", {"name": name, "os": d.get("OS", "")}, int(online)))
        seen = now if online else _ts(d.get("LastSeen"))
        if seen:
            out.append(("mc_tailscale_peer_last_seen_seconds", {"name": name}, seen))
    return out


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _num(v):
    """Full precision: integers as-is, floats via repr (shortest exact form)."""
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 1e18 else repr(v)


def render(metrics):
    """Prometheus text format, one # TYPE line per metric name."""
    lines, typed = [], set()
    for name, labels, val in metrics:
        if name not in typed:
            typed.add(name)
            lines.append(f"# TYPE {name} gauge")
        lab = ",".join(f'{k}="{_esc(v)}"' for k, v in sorted(labels.items()))
        lines.append(f"{name}{{{lab}}} {_num(val)}" if lab else f"{name} {_num(val)}")
    return "\n".join(lines) + "\n"
