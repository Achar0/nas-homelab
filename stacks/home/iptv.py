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


# ---------- which channels are kept, and under which menu section ----------

CHINESE, ENGLISH, ITALIAN, MOTORSPORT, FINANCE = SECTIONS = ("Lingua cinese", "Lingua inglese", "Lingua italiana", "Motorsport", "Finanza")
_LANGUAGES = {"zho": CHINESE, "cmn": CHINESE, "yue": CHINESE, "eng": ENGLISH, "ita": ITALIAN}
_BLOCKED = {"religious", "kids", "music", "xxx"}    # iptv-org categories, also found in group-title
_BLOCKED_NAME = re.compile(
    r"church|gospel|christ|jesus|islam|quran|bible|catholic|allah|faith|prayer|ministr|\bgod\b|\btbn\b|\bewtn\b|\bdaystar\b"
    r"|padre pio|telepace|tv2000|telemaria|radio maria|佛|基督|教会|法轮"     # religion the catalog doesn't label
    r"|\bkids?\b|cartoon|boomerang|disney|nick|boing|rai yoyo|rai gulp|frisbee|\bk2\b|rainbow ruby|yu-gi-oh|toonami|icarly|family zone|gametoon|少儿|卡通|动漫|动画|儿童|cctv-?\s*14\b"
    r"|his glory|swamiji|\bkcm\b|the walk tv|impact network|sophia tv|tele chiara|\bcbn\b|scientology|supreme master|\btct\b|praise tv"
    r"|world harvest|dove channel|\btln\b"
    r"|\bradio\b|\bfm\b|\bmtv\b|\bvh1\b|stingray|\brtl 102|deejay tv|\brds\b|live music|\brevolt\b|brit asia|wu tang|stereo 5|\bfuse\b|音乐|cctv-?\s*15\b"
    r"|press tv|\brt india\b|rtr-planeta|tv brics|\bntd\b|girlfriends films"     # state propaganda, adult studio
    r"|newsmax|\boan\b|one america|america'?s voice|blaze live|free speech tv|young turks|salem news|right now tv|the first tv"
    r"|fox news|\bms now\b|talktv|telesur|\bvoa tv\b|\bdkn\b"     # partisan news
    r"|espa[nñ]ol|telemundo|univision|crimenes|\bcine (aventura|romantico)\b|mas adrenalina|investiga us|wedo tv amor|en francais", re.I)     # foreign feeds the catalog files under English
_OFFICIAL_CHINESE = re.compile(
    r"^(cctv|cgtn|cetv)|卫视|satellite|凤凰|phoenix|^(hunan|anhui|guangdong) tv|^zhejiang international|^(golden )?jade|tvb|viutv|rthk|hoy"
    r"|^(ctv|cts|ftv|pts|ebc|tvbs|set|tti|ttv)\b|hakka tv|channel 8 \(singapore|三立|东森|民视|公视|华视|中视|中天", re.I)
_MOTORSPORT = re.compile(r"motorsport|motorvision|\bf1\b|formula 1|nascar|floracing|rally tv|\bracer\b|aci sport|\bmotogp\b|\bwrc\b|\bindycar\b", re.I)
_FINANCE = re.compile(r"bloomberg|cnbc|yahoo!? finance|fox business|financ|财经|class cnbc", re.I)


def catalog(feeds, channels):
    """{tvg-id: {"languages", "categories"}} from the iptv-org data, leaving out adult channels and foreign feeds."""
    info = {c["id"]: c for c in channels}
    out = {}
    for f in feeds:
        c = info.get(f["channel"])
        if c and not c.get("is_nsfw") and f["languages"] and set(f["languages"]) <= set(_LANGUAGES):
            out[f'{f["channel"]}@{f["id"]}'] = {"languages": f["languages"], "categories": c.get("categories") or []}
    return out


def _attribute(info, name):
    found = re.search(rf'{name}="([^"]*)"', info)
    return found[1] if found else ""


def section(row, known):
    """The menu section this channel belongs to, or None when it's dropped."""
    info = row["info"]
    name = info.rsplit(",", 1)[-1].strip()
    tvg_id, group = _attribute(info, "tvg-id"), _attribute(info, "group-title")
    if _BLOCKED_NAME.search(name) or _BLOCKED & set(group.lower().split(";")):
        return None
    if not tvg_id:         # the Chinese lists have no ids: only recognised broadcasters get through
        return CHINESE if _OFFICIAL_CHINESE.search(name) and group not in ("卡通频道",) else None
    entry = known.get(tvg_id)
    if not entry or _BLOCKED & set(entry["categories"]):
        return None
    languages = {_LANGUAGES[x] for x in entry["languages"]}
    if CHINESE in languages and _OFFICIAL_CHINESE.search(name):
        return CHINESE
    if _MOTORSPORT.search(name):
        return MOTORSPORT
    if _FINANCE.search(name) or "business" in entry["categories"] or "business" in group.lower().split(";"):
        return FINANCE
    return ENGLISH if ENGLISH in languages else ITALIAN if ITALIAN in languages else None


def _grouped(info, title):
    bare = re.sub(r'\s+group-title="[^"]*"', "", info)
    return re.sub(r"^(#EXTINF:[^ ,]*)", rf'\1 group-title="{title}"', bare, count=1)


def curate(rows, known):
    """The allowed channels, each moved to its menu section, in menu order (players list groups as they first appear)."""
    picked = [(section(r, known), r) for r in rows]
    return [{**r, "info": _grouped(r["info"], s)} for name in SECTIONS for s, r in picked if s == name]


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
