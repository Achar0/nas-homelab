"""What needs attention: rules from the design, as pure functions.

evaluate(inputs, state, now) turns the latest readings into pinned items, at most one urgent
takeover, and the pushes to send. `state` (persisted by the server) remembers each incident:
when it started, whether it was pushed, resolved, dismissed or acknowledged.

An incident is one continuous stretch of a condition. When it clears it stays listed as
resolved for 24 h; if it comes back later it is a new incident (alerts and pushes again).
"""
KEEP_RESOLVED = 24 * 3600
NETWATCH_ACTIVE = 300          # a Netwatch entry seen in the last 5 min counts as ongoing
INTRUSION_URGENT_AFTER = 180   # attack must persist 3 min before it takes over the screen
KUMA_URGENT_AFTER = 120        # service down > 2 min
PUSH_COOLDOWN = 3600           # the same problem pushes at most once an hour (flapping services)
PUSH_CAP_PER_HOUR = 10         # and never more than 10 urgent pushes an hour in total (scans from many IPs)
LEVELS = {"urgent": 0, "normal": 1}


def _cond(cid, src, level, title, detail, app, since=None, urgent_after=None, live=True):
    # live=False: still listed (recently seen) but not evidence that it is *still* happening,
    # so it can never escalate on its own
    return {"id": cid, "src": src, "level": level, "title": title, "detail": detail, "app": app,
            "since": since, "urgent_after": urgent_after, "live": live}


def _netwatch(nw, now):
    out = []
    for it in nw.get("items") or []:
        if not it.get("flag") or it.get("scope") != "internet":
            continue
        if not (it.get("live") or now - it.get("last", 0) < NETWATCH_ACTIVE):
            continue
        where = ", ".join(x for x in ((it.get("geo") or {}).get("city"), (it.get("geo") or {}).get("country")) if x)
        what = ", ".join(it.get("services") or [])
        detail = f"{it['ip']}{f' ({where})' if where else ''} · {what} · {it['flag'][0]}"
        if it.get("dir") == "in":
            # timed from when *we* first see it ongoing: Netwatch's `first` spans 24 h and would
            # turn an old sighting plus a new one into a fake 3-hour attack
            out.append(_cond(f"intrusion:{it['ip']}", "netwatch", "normal", "Possible intrusion", detail, "netwatch",
                             urgent_after=INTRUSION_URGENT_AFTER, live=bool(it.get("live"))))
        else:
            out.append(_cond(f"flagged-out:{it['ip']}", "netwatch", "normal", "Connection to a flagged address",
                             detail, "netwatch"))
    return out


def _kuma(kuma):
    return [_cond(f"kuma-down:{name}", "kuma", "normal", f"{name} is down", "Uptime Kuma reports it unreachable",
                  "kuma", urgent_after=KUMA_URGENT_AFTER)
            for name, status in kuma.items() if status == 0]


def _prom(p):
    out = []
    if p.get("md_active") is not None and p.get("md_required") and p["md_active"] < p["md_required"]:
        out.append(_cond("raid", "prom", "urgent", "RAID degraded",
                         f"{p['md_active']} of {p['md_required']} drives active", "mission"))
    for dev, ok in (p.get("smart_status") or {}).items():
        if ok == 0:
            out.append(_cond(f"smart:{dev}", "prom", "urgent", f"Drive {dev} failing", "SMART health check failed", "mission"))
    for dev, t in (p.get("drive_temp") or {}).items():
        if t is not None and t > 50:
            out.append(_cond(f"hot:{dev}", "prom", "normal", f"Drive {dev} running hot", f"{round(t)} °C", "mission"))
    if p.get("free_ratio") is not None and p["free_ratio"] < 0.15:
        out.append(_cond("space", "prom", "normal", "Free space low", f"{round(p['free_ratio'] * 100)}% free on the RAID volume", "mission"))
    last, med = p.get("speed_last"), p.get("speed_median")
    if last and med and last < 0.5 * med:
        out.append(_cond("speed", "prom", "normal", "Slow internet",
                         f"Last speed test {round(last / 1e6)} Mb/s, usually {round(med / 1e6)} Mb/s", "speedtest"))
    return out


def _restarts(r):
    return [_cond(f"restarts:{name}", "docker", "urgent", f"{name} keeps restarting", f"{n} restarts in 10 min", "dockge")
            for name, n in r.items() if n >= 3]


def _missing(ab):
    return [_cond(f"missing:{m['show']} {m['episode']}", "ab", "normal", "Episode not downloaded",
                  f"{m['show']} {m['episode']} appeared in the feed but hasn't downloaded", "qbittorrent")
            for m in ab]


RULES = {"netwatch": _netwatch, "kuma": _kuma, "prom": _prom, "restarts": _restarts, "ab_missing": _missing}
SRC_OF_INPUT = {"netwatch": "netwatch", "kuma": "kuma", "prom": "prom", "restarts": "docker", "ab_missing": "ab"}


def evaluate(inputs, state, now):
    incidents = state.setdefault("incidents", {})
    active, known_srcs = {}, set()
    for key, rule in RULES.items():
        data = inputs.get(key)
        if data is None:
            continue   # source unavailable: neither raise nor resolve its incidents
        known_srcs.add(SRC_OF_INPUT[key])
        for c in rule(data, now) if key == "netwatch" else rule(data):
            active[c["id"]] = c

    pushes = []
    last_push = state.setdefault("last_push", {})
    log = state["push_log"] = [t for t in state.get("push_log", []) if now - t < 3600]
    for cid, c in active.items():
        inc = incidents.get(cid)
        if inc is None or inc.get("resolved_at") is not None:   # new incident
            inc = incidents[cid] = {"started": c["since"] or now, "pushed": False, "dismissed": False,
                                    "acked": False, "resolved_at": None, "live_since": None}
        if c["live"] and inc.get("live_since") is None:
            inc["live_since"] = now
        level = c["level"]
        if (c["urgent_after"] is not None and c["live"] and inc.get("live_since") is not None
                and now - inc["live_since"] >= c["urgent_after"]):
            level = "urgent"
        if level == "urgent" and inc.get("level") == "normal":
            inc["dismissed"] = inc["acked"] = False   # escalated: a dismissal of the mild version doesn't count
        inc.update(level=level, title=c["title"], detail=c["detail"], src=c["src"], app=c["app"])
        if level == "urgent" and not inc["pushed"]:
            inc["pushed"] = True
            if now - last_push.get(cid, 0) >= PUSH_COOLDOWN and len(log) < PUSH_CAP_PER_HOUR:
                last_push[cid] = now
                log.append(now)
                pushes.append({"id": cid, "title": c["title"], "detail": c["detail"]})
    for cid in [k for k, t in last_push.items() if now - t > PUSH_COOLDOWN]:
        del last_push[cid]

    for cid, inc in list(incidents.items()):
        if cid not in active and inc.get("resolved_at") is None and inc.get("src") in known_srcs:
            inc["resolved_at"] = now
            if inc.get("level") == "urgent" and not inc.get("pushed"):
                inc["level"] = "normal"
        if inc.get("resolved_at") is not None and now - inc["resolved_at"] > KEEP_RESOLVED:
            del incidents[cid]

    items = [{"id": cid, "level": inc["level"], "title": inc["title"], "detail": inc["detail"], "app": inc["app"],
              "since": inc["started"], "resolved": inc["resolved_at"] is not None, "acked": bool(inc.get("acked"))}
             for cid, inc in incidents.items() if not inc["dismissed"]]
    # priority: active urgent, acknowledged urgent (banner), normal, then resolved; newest first within each
    items.sort(key=lambda i: (i["resolved"], LEVELS[i["level"]], i["acked"], -i["since"]))
    urgent = next((i for i in items if i["level"] == "urgent" and not i["resolved"]
                   and not incidents[i["id"]]["acked"]), None)
    return items, urgent, pushes


def _mark(state, cid, field):
    inc = state.get("incidents", {}).get(cid)
    if inc is None:
        return False
    inc[field] = True
    return True


def dismiss(state, cid):
    """Hide an item until its condition clears and comes back."""
    return _mark(state, cid, "dismissed")


def ack(state, cid):
    """Close the urgent takeover (the item stays pinned while the problem lasts)."""
    return _mark(state, cid, "acked")
