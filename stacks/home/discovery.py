"""Notice containers that appear on the NAS, for the Services & dock section of Settings. Pure.

Docker can't always say where a web page lives: a host-network container reports no ports, and
one with several doesn't say which is the page. So the row asks the owner when it isn't clear.
Nothing here ever puts a service on the dock.
"""
import re

import settings

_LOOPBACK = ("127.0.0.1", "::1")
_NAME_PORT = re.compile(r"-(\d{2,5})$")


def name_port(name):
    """9000 for "thing-9000". None if there is no usable number (so "app-1" isn't a port)."""
    m = _NAME_PORT.search(name)
    port = int(m.group(1)) if m else 0
    return port if 1 <= port <= 65535 else None


def published_ports(container):
    """Ports reachable from other machines, each once, sorted."""
    return sorted({p["PublicPort"] for p in container.get("Ports") or []
                   if p.get("PublicPort") and p.get("IP") not in _LOOPBACK})


def _friendly(name):
    words = re.sub(r"[-_.]+", " ", _NAME_PORT.sub("", name)).strip()
    return (words.title() or name)[:settings.NAME_LIMIT]


def _new_row(name, container):
    ports = published_ports(container)
    port = ports[0] if len(ports) == 1 else (name_port(name) if not ports else None)
    row = settings.service(f"c-{name}", _friendly(name), settings.PLAIN_ICON, True, port, name, on_dock=False)
    row.update(state="new", port_options=ports if len(ports) > 1 else [])
    return row


def _names(containers):
    """{container name: running?}"""
    return {c["Names"][0].lstrip("/"): c.get("State") == "running" for c in containers if c.get("Names")}


def apply(cfg, containers):
    """Update cfg from a Docker listing. True if it changed. None means Docker couldn't be read: change nothing."""
    if containers is None:
        return False
    names = _names(containers)
    changed = False
    if cfg["known_containers"] is None:   # first scan: everything already here is known, not new
        cfg["known_containers"] = sorted(names)
        changed = True
    for c in containers:
        name = c["Names"][0].lstrip("/") if c.get("Names") else None
        if name and name not in cfg["known_containers"]:
            cfg["known_containers"].append(name)
            cfg["services"].append(_new_row(name, c))
            changed = True
    for s in cfg["services"]:
        if s["container"] and s["running"] != names.get(s["container"], False):
            s["running"] = names.get(s["container"], False)
            changed = True
    return changed


def remove(cfg, service_id):
    """Drop a row. Its container is forgotten too, so it shows as new if it ever comes back."""
    row = next((s for s in cfg["services"] if s["id"] == service_id), None)
    if row is None:
        return
    cfg["services"].remove(row)
    if row["container"] and cfg["known_containers"] and row["container"] in cfg["known_containers"]:
        cfg["known_containers"].remove(row["container"])
