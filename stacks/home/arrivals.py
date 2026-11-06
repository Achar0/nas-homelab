"""Just arrived / downloading, from qBittorrent's torrent list (pure)."""
import os
import re

WINDOW = 48 * 3600
STALLED = {"stalledDL", "metaDL", "missingFiles", "error"}

_PATH = re.compile(r"(?:^|/)(?P<show>[^/]+?) S(?P<s>\d{1,2})E(?P<e>\d{1,4})(?:-E\d+)?\.[A-Za-z0-9]+$")
_FANSUB = re.compile(r"^\[[^\]]+\]\s*(?P<show>.+?)\s+-\s+(?P<e>\d{1,4})(?:v\d)?(?:\s*[\[(].*)?(?:\.[A-Za-z0-9]+)?$")
_BATCH = re.compile(r"^(?:\[[^\]]+\])?\[(?P<show>[^\]]+)\]\[(?P<range>\d{1,4}-\d{1,4})\]")


def show_episode(name, path):
    """Best guess at (show, episode label) from the renamed path, else the torrent name."""
    show, ep = _show_episode(name, path)
    return show.replace("_", " ").strip(), ep


def _show_episode(name, path):
    m = _PATH.search(path or "")
    if m:
        return m["show"], f"S{int(m['s']):02d}E{int(m['e']):02d}"
    m = _FANSUB.match(name)
    if m:
        return m["show"], f"E{int(m['e']):02d}"
    m = _BATCH.match(name)
    if m:
        return m["show"], m["range"]
    base = os.path.splitext(name)[0]
    return re.sub(r"\[[^\]]*\]", "", base).strip(" -._") or base, ""


def build(torrents, now):
    arrived, downloading = [], []
    for t in torrents:
        show, ep = show_episode(t["name"], t.get("content_path", ""))
        if t["progress"] >= 1:
            if t.get("completion_on", 0) > now - WINDOW:
                arrived.append({"show": show, "ep": ep, "at": t["completion_on"]})
        else:
            stalled = t["state"] in STALLED
            downloading.append({"show": show, "ep": ep, "progress": round(t["progress"], 3),
                                "eta": None if stalled or t.get("eta", 0) >= 8640000 else t["eta"], "stalled": stalled})
    arrived.sort(key=lambda a: -a["at"])
    return {"arrived": arrived[:12], "downloading": downloading}
