"""IPTV channel health and the clean playlist (pure: the network comes in as `fetch`).

A channel is judged by downloading a real video segment, because a stream that answers can still be too
slow to watch: `online` arrives comfortably faster than it plays, `lag` doesn't, `offline` can't be played.
`fetch(url, limit, timeout, keep=None, headers=None)` returns (first `keep` bytes or all of them, seconds
taken, final url) and raises when it fails.
"""
import concurrent.futures
import ipaddress
import re
import secrets
import urllib.parse

FAST_ENOUGH = 1.5           # segment duration / download time
MIN_CHANNELS = 20           # fewer than this means the check itself went wrong: keep the previous playlist
PLAYLIST_LIMIT = 300_000
SEGMENT_LIMIT = 20_000_000
SEGMENT_KEEP = 4096         # enough to tell video from an error page; the rest is only timed
MIN_SEGMENT = 1024          # bytes: real segments are far larger than any error answer
PLAYLIST_TIMEOUT = 8
SEGMENT_TIMEOUT = 20
FROM_END = 3                # players start a few segments back: the newest may still be arriving at the edge
WORKERS = 8
NAME_LIMIT = 80
ADDRESS_LIMIT = 2000
FILE_LIMIT = 5_000_000      # bytes of an uploaded playlist
_OPTION_HEADERS = {"http-referrer": "Referer", "http-user-agent": "User-Agent"}


def _text(text):
    return text.lstrip("﻿ \t\r\n")


def header(text):
    """What follows #EXTM3U on the first line (the channel guide address), to carry over to the clean playlist."""
    first = _text(text).split("\n", 1)[0].strip()
    return " " + first[7:].strip() if first.startswith("#EXTM3U") and first[7:].strip() else ""


def parse(text):
    """Channels as {"info": #EXTINF line, "url": http(s) address, "opts": its #EXTVLCOPT lines}."""
    text = _text(text)
    if not text.startswith("#EXTM3U"):
        return []
    rows, info, opts = [], None, []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            info, opts = line, []
        elif line.startswith("#EXTVLCOPT") and info:
            opts.append(line)
        elif line and not line.startswith("#") and info:
            if line.startswith(("http://", "https://")):
                rows.append({"info": info, "url": line, "opts": opts})
            info, opts = None, []
    return rows


def is_public(url, resolve):
    """Whether `url` is http(s) on a public address. Lists come from strangers: they mustn't reach the NAS's own services."""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        addresses = resolve(parts.hostname)
        return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
    except (OSError, ValueError):
        return False


def _headers(opts):
    out = {}
    for line in opts:
        key, _, value = line.partition(":")[2].partition("=")
        if key.strip().lower() in _OPTION_HEADERS and value.strip():
            out[_OPTION_HEADERS[key.strip().lower()]] = value.strip()
    return out or None


def _uris(lines):
    return [line for line in lines if line and not line.startswith("#")]


def _media_playlist(url, get):
    """(lines, address) of the playlist listing segments, following a master playlist to its first variant."""
    body, _, final = get(url, PLAYLIST_LIMIT, PLAYLIST_TIMEOUT)
    lines = [x.strip() for x in body.decode("utf-8", "replace").splitlines()]
    if any(x.startswith("#EXT-X-STREAM-INF") for x in lines):
        body, _, final = get(urllib.parse.urljoin(final, _uris(lines)[0]), PLAYLIST_LIMIT, PLAYLIST_TIMEOUT)
        lines = [x.strip() for x in body.decode("utf-8", "replace").splitlines()]
    return lines, final


def _segments(lines):
    """[(duration, uri)], taking the first address after each #EXTINF (other tags can sit in between)."""
    out, duration = [], None
    for line in lines:
        if line.startswith("#EXTINF:"):
            duration = float(re.match(r"#EXTINF:([\d.]+)", line)[1])
        elif line and not line.startswith("#") and duration is not None:
            out.append((duration, line))
            duration = None
    return out


def _is_video(head):
    return len(head) >= MIN_SEGMENT and not head.lstrip()[:1] in (b"<", b"{")


def probe(url, fetch, opts=()):
    headers = _headers(opts)

    def get(u, limit, timeout, keep=None):
        return fetch(u, limit, timeout, keep, headers)
    try:
        lines, final = _media_playlist(url, get)
        segments = _segments(lines)
        duration, uri = segments[max(len(segments) - FROM_END, 0)]
        head, took, _ = get(urllib.parse.urljoin(final, uri), SEGMENT_LIMIT, SEGMENT_TIMEOUT, SEGMENT_KEEP)
    except Exception:  # noqa: BLE001 - dead hosts and malformed answers are the normal case here
        return "offline"   # includes streams that aren't HLS: they can't be measured, so they don't count as good
    if not _is_video(head):
        return "offline"
    return "online" if duration >= FAST_ENOUGH * took else "lag"


def unique(rows):
    seen, out = set(), []
    for r in rows:
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    return out


def counts(rows):
    rows = unique(rows)
    c = {s: sum(1 for r in rows if r.get("state") == s) for s in ("online", "lag", "offline")}
    return {**c, "total": len(rows)}


def _fast(rows):
    return [r for r in unique(rows) if r.get("state") == "online"]


def usable(rows):
    return len(_fast(rows)) >= MIN_CHANNELS


def clean(rows, head=""):
    lines = [f"#EXTM3U{head}"]
    for r in _fast(rows):
        lines += [r["info"], *r.get("opts", []), r["url"]]
    return "\n".join(lines) + "\n"


# ---------- the lists ----------

def valid_address(url):
    return len(url) <= ADDRESS_LIMIT and url.startswith(("http://", "https://"))


def new_list(kind, name, source):
    """A list to check: `kind` is "url" (source is its address) or "file" (source is the file's name)."""
    if not name.strip():
        path = urllib.parse.unquote(urllib.parse.urlsplit(source).path) if kind == "url" else source
        name = path.rsplit("/", 1)[-1] or source
    out = {"id": secrets.token_hex(6), "name": name.strip()[:NAME_LIMIT], "kind": kind, "rows": [], "checked": 0, "error": ""}
    return {**out, "url": source} if kind == "url" else out


def view(lst):
    return {**{k: lst.get(k, "") for k in ("id", "name", "kind", "url", "checked", "error")}, "counts": counts(lst["rows"])}


def channels(lst):
    out = []
    for r in lst["rows"]:
        group = re.search(r'group-title="([^"]*)"', r["info"])
        out.append({"name": r["info"].rsplit(",", 1)[-1].strip(), "group": group[1] if group else "",
                    "state": r.get("state", "offline"), "url": r["url"]})
    return out


def check_lists(lists, read, fetch, now, workers=WORKERS):
    """(the lists with fresh states, whether every list could be read). `read(list)` gives its text or raises."""
    fresh, complete = [], True
    for lst in lists:
        try:
            text = read(lst)
            rows = parse(text)
            if not rows:
                raise ValueError("no channels")
            fresh.append({**lst, "rows": rows, "head": header(text), "checked": now, "error": ""})
        except Exception as e:  # noqa: BLE001 - one bad list must not stop the others, and keeps its last results
            complete = False
            fresh.append({**lst, "error": type(e).__name__})
    pending = {r["url"]: r for lst in fresh if not lst["error"] for r in lst["rows"]}
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        found = dict(zip(pending, pool.map(lambda r: probe(r["url"], fetch, r["opts"]), pending.values())))
    for lst in fresh:
        if not lst["error"]:
            lst["rows"] = [{**r, "state": found[r["url"]]} for r in lst["rows"]]
    return fresh, complete
