"""IPTV channel health and the clean playlist (pure: the network comes in as `fetch`).

A channel is judged by downloading a real video segment, because a stream that answers can still be too
slow to watch: `online` arrives comfortably faster than it plays, `lag` doesn't, `offline` can't be played.
`fetch(url, limit, timeout)` returns (bytes, seconds taken, final url) and raises when it fails.
"""
import re
import urllib.parse

FAST_ENOUGH = 1.5           # segment duration / download time
MIN_CHANNELS = 20           # fewer than this means the check itself went wrong: keep the previous playlist
PLAYLIST_LIMIT = 300_000
SEGMENT_LIMIT = 20_000_000
PLAYLIST_TIMEOUT = 8
SEGMENT_TIMEOUT = 20


def parse(text):
    """The channels of an #EXTM3U playlist as {"info": its #EXTINF line, "url": its http(s) address}."""
    if not text.lstrip().startswith("#EXTM3U"):
        return []
    rows, info = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            info = line
        elif line and not line.startswith("#") and info:
            if line.startswith(("http://", "https://")):
                rows.append({"info": info, "url": line})
            info = None
    return rows


def _uris(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def _media_playlist(url, fetch):
    """(text, address) of the playlist listing segments, following a master playlist to its first variant."""
    body, _, final = fetch(url, PLAYLIST_LIMIT, PLAYLIST_TIMEOUT)
    text = body.decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" in text:
        body, _, final = fetch(urllib.parse.urljoin(final, _uris(text)[0]), PLAYLIST_LIMIT, PLAYLIST_TIMEOUT)
        text = body.decode("utf-8", "replace")
    return text, final


def probe(url, fetch):
    try:
        text, final = _media_playlist(url, fetch)
        lines = [line.strip() for line in text.splitlines()]
        last = max(i for i, line in enumerate(lines) if line.startswith("#EXTINF"))
        duration = float(re.match(r"#EXTINF:([\d.]+)", lines[last])[1])
        _, took, _ = fetch(urllib.parse.urljoin(final, lines[last + 1]), SEGMENT_LIMIT, SEGMENT_TIMEOUT)
    except Exception:  # noqa: BLE001 - dead hosts and malformed answers are the normal case here
        return "offline"   # includes streams that aren't HLS: they can't be measured, so they don't count as good
    return "online" if duration >= FAST_ENOUGH * took else "lag"


def counts(rows):
    c = {s: sum(1 for r in rows if r["state"] == s) for s in ("online", "lag", "offline")}
    return {**c, "total": len(rows)}


def _fast(rows):
    seen, out = set(), []
    for r in rows:
        if r["state"] == "online" and r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    return out


def usable(rows):
    return sum(1 for r in rows if r["state"] == "online") >= MIN_CHANNELS


def clean(rows):
    return "#EXTM3U\n" + "".join(f"{r['info']}\n{r['url']}\n" for r in _fast(rows))
