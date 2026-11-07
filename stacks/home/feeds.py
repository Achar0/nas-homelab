"""News feeds: RSS/Atom -> plain-text items, with near-duplicate stories merged.

Pure functions; fetch_all takes the fetcher as an argument so tests need no network.
Feed text is untrusted: everything is reduced to plain text here.
"""
import email.utils
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
MAX_SUMMARY = 600
DEDUPE_WINDOW = 12 * 3600


class _Text(HTMLParser):
    """Collects visible text, skipping <script>/<style>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def clean(text):
    """HTML -> plain text, whitespace collapsed, cut at a word boundary."""
    p = _Text()
    p.feed(html.unescape(text or "") if "<" not in (text or "") else text or "")
    p.close()
    out = re.sub(r"\s+", " ", html.unescape("".join(p.parts))).strip()
    if len(out) > MAX_SUMMARY:
        out = out[:MAX_SUMMARY].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"
    return out


def _date(s):
    if not s:
        return 0
    s = s.strip()
    try:
        return int(email.utils.parsedate_to_datetime(s).timestamp())   # RSS: RFC 822
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())  # Atom: ISO 8601
    except ValueError:
        return 0


def _text(el, *tags):
    for t in tags:
        e = el.find(t)
        if e is not None and (e.text or "").strip():
            return e.text
    return ""


def parse(data, source, topic, lang):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"{source}: not a feed ({e})") from None
    out = []
    if root.tag == ATOM + "feed":
        for e in root.findall(ATOM + "entry"):
            link = next((l.get("href") for l in e.findall(ATOM + "link") if l.get("rel", "alternate") == "alternate"), "")
            out.append((_text(e, ATOM + "title"), _text(e, ATOM + "summary", ATOM + "content"), link,
                        _text(e, ATOM + "published", ATOM + "updated")))
    elif root.find("channel") is not None:
        for e in root.find("channel").findall("item"):
            out.append((_text(e, "title"), _text(e, "description", CONTENT), _text(e, "link").strip(), _text(e, "pubDate")))
    else:
        raise ValueError(f"{source}: not RSS or Atom")
    items = []
    for title, summary, link, date in out:
        title = clean(title)
        if not title or not link.startswith("http"):
            continue
        items.append({"id": hashlib.sha1(link.encode()).hexdigest()[:12], "title": title, "summary": clean(summary),
                      "link": link, "source": source, "topic": topic, "lang": lang, "published": _date(date)})
    return items


def check(data):
    """The cleaned title of an RSS or Atom feed ("" if it has none). Raises ValueError if it isn't one."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ValueError("not a feed") from None
    if root.tag == ATOM + "feed":
        return clean(_text(root, ATOM + "title"))
    channel = root.find("channel")
    if channel is None:
        raise ValueError("not RSS or Atom")
    return clean(_text(channel, "title"))


def _words(title):
    return set(re.sub(r"[^\w\s]", " ", title.lower()).split())


def _same_story(a, b):
    if abs(a["published"] - b["published"]) > DEDUPE_WINDOW:
        return False
    wa, wb = _words(a["title"]), _words(b["title"])
    if wa == wb:
        return True
    # tolerate plural/singular and small edits: compare rough stems (no trailing s, first 5 letters)
    stem = lambda w: (w[:-1] if len(w) > 3 and w.endswith("s") else w)[:5]
    sa, sb = {stem(w) for w in wa}, {stem(w) for w in wb}
    return bool(sa and sb) and len(sa & sb) / max(len(sa), len(sb)) > 0.8


def dedupe(items):
    """Keep the first-published item of each story."""
    kept = []
    for it in sorted(items, key=lambda x: x["published"]):
        if not any(_same_story(it, k) for k in kept):
            kept.append(it)
    return kept


def fetch_all(config, fetch):
    """Fetch and parse every feed; a failing feed is reported, never fatal."""
    items, errors = [], []
    for f in config:
        try:
            items += parse(fetch(f["url"]), f["name"], f["topic"], f["lang"])
        except Exception:  # noqa: BLE001 - one bad feed must not hide the rest
            errors.append(f["name"])
    return items, errors


def balance(items, per_source=8):
    """Newest first, at most per_source items from each feed (busy feeds can't drown the rest)."""
    seen, out = {}, []
    for it in sorted(items, key=lambda x: -x["published"]):
        n = seen.get(it["source"], 0)
        if n < per_source:
            seen[it["source"]] = n + 1
            out.append(it)
    return out
