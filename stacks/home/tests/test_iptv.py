import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import iptv  # noqa: E402

LIST = """#EXTM3U x-tvg-url="http://example.org/e.xml"
#EXTINF:-1 tvg-id="a" group-title="News",Channel A
http://a.example/live.m3u8
#EXTINF:-1 group-title="News",Channel A
http://a2.example/live.m3u8

#EXTINF:-1,Channel B
https://b.example/live.m3u8
#EXTVLCOPT:http-user-agent=x
#EXTINF:-1,No Url
"""

MEDIA = "#EXTM3U\n#EXTINF:6.0,\nold.ts\n#EXTINF:6.0,\nnew.ts\n"
MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nvariant/index.m3u8\n"


def fetcher(pages):
    """pages: url -> (text or bytes, seconds taken); anything else fails like a dead host."""
    calls = []
    def fetch(url, limit, timeout):
        calls.append(url)
        if url not in pages:
            raise OSError("dead")
        body, took = pages[url]
        return body.encode() if isinstance(body, str) else body, took, url
    fetch.calls = calls
    return fetch


class Parse(unittest.TestCase):
    def test_entries_keep_their_info_line(self):
        rows = iptv.parse(LIST)
        self.assertEqual([r["url"] for r in rows],
                         ["http://a.example/live.m3u8", "http://a2.example/live.m3u8", "https://b.example/live.m3u8"])
        self.assertEqual(rows[2]["info"], "#EXTINF:-1,Channel B")

    def test_not_a_playlist(self):
        self.assertEqual(iptv.parse("<html>nope</html>"), [])

    def test_entry_without_url_is_skipped(self):
        self.assertEqual(len(iptv.parse(LIST)), 3)

    def test_non_http_sources_are_skipped(self):
        self.assertEqual(iptv.parse("#EXTM3U\n#EXTINF:-1,X\nrtp://239.0.0.1:1234\n"), [])


class Probe(unittest.TestCase):
    def test_fast_segment_is_online(self):
        f = fetcher({"http://x/l.m3u8": (MEDIA, .1), "http://x/new.ts": (b"v", 4.0)})
        self.assertEqual(iptv.probe("http://x/l.m3u8", f), "online")

    def test_uses_the_newest_segment(self):
        f = fetcher({"http://x/l.m3u8": (MEDIA, .1), "http://x/new.ts": (b"v", 1.0)})
        iptv.probe("http://x/l.m3u8", f)
        self.assertEqual(f.calls[-1], "http://x/new.ts")

    def test_just_under_the_margin_is_lag(self):
        f = fetcher({"http://x/l.m3u8": (MEDIA, .1), "http://x/new.ts": (b"v", 4.1)})
        self.assertEqual(iptv.probe("http://x/l.m3u8", f), "lag")

    def test_master_playlist_follows_the_first_variant(self):
        f = fetcher({"http://x/m.m3u8": (MASTER, .1), "http://x/variant/index.m3u8": (MEDIA, .1),
                     "http://x/variant/new.ts": (b"v", 1.0)})
        self.assertEqual(iptv.probe("http://x/m.m3u8", f), "online")

    def test_dead_host_is_offline(self):
        self.assertEqual(iptv.probe("http://x/l.m3u8", fetcher({})), "offline")

    def test_dead_segment_is_offline(self):
        self.assertEqual(iptv.probe("http://x/l.m3u8", fetcher({"http://x/l.m3u8": (MEDIA, .1)})), "offline")

    def test_response_that_is_not_hls_is_offline(self):
        self.assertEqual(iptv.probe("http://x/l.m3u8", fetcher({"http://x/l.m3u8": ("<html>", .1)})), "offline")


class Results(unittest.TestCase):
    ROWS = [{"info": "#EXTINF:-1,A", "url": "http://a/1", "state": "online"},
            {"info": "#EXTINF:-1,B", "url": "http://b/1", "state": "lag"},
            {"info": "#EXTINF:-1,C", "url": "http://c/1", "state": "offline"}]

    def test_counts(self):
        self.assertEqual(iptv.counts(self.ROWS), {"online": 1, "lag": 1, "offline": 1, "total": 3})

    def test_clean_playlist_has_only_fast_channels(self):
        self.assertEqual(iptv.clean(self.ROWS), "#EXTM3U\n#EXTINF:-1,A\nhttp://a/1\n")

    def test_same_url_in_two_lists_is_kept_once(self):
        rows = [self.ROWS[0], dict(self.ROWS[0])]
        self.assertEqual(iptv.clean(rows).count("http://a/1"), 1)

    def test_too_few_channels_is_not_a_usable_playlist(self):
        self.assertFalse(iptv.usable([self.ROWS[0]] * (iptv.MIN_CHANNELS - 1)))
        self.assertTrue(iptv.usable([self.ROWS[0]] * iptv.MIN_CHANNELS))


if __name__ == "__main__":
    unittest.main()
