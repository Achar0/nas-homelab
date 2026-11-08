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
#EXTVLCOPT:http-referrer=http://ref.example/
#EXTVLCOPT:http-user-agent=Custom/1
https://b.example/live.m3u8
#EXTINF:-1,No Url
"""

MEDIA = "#EXTM3U\n" + "".join(f"#EXTINF:6.0,\ns{i}.ts\n" for i in range(6))
MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nvariant/index.m3u8\n"
VIDEO = b"\x47" + b"v" * 4000


def fetcher(pages):
    """pages: url -> (text or bytes, seconds taken); anything else fails like a dead host."""
    calls = []

    def fetch(url, limit, timeout, keep=None, headers=None):
        calls.append((url, headers))
        if url not in pages:
            raise OSError("dead")
        body, took = pages[url]
        body = body.encode() if isinstance(body, str) else body
        return (body[:keep] if keep else body), took, url
    fetch.calls = calls
    return fetch


def row(n, state="online"):
    return {"info": f"#EXTINF:-1,{n}", "url": f"http://{n}/1", "opts": [], "state": state}


def public(host):
    return {"8.8.8.8"}


class Parse(unittest.TestCase):
    def test_entries_keep_their_info_line(self):
        rows = iptv.parse(LIST)
        self.assertEqual([r["url"] for r in rows],
                         ["http://a.example/live.m3u8", "http://a2.example/live.m3u8", "https://b.example/live.m3u8"])
        self.assertEqual(rows[2]["info"], "#EXTINF:-1,Channel B")

    def test_vlc_options_are_kept(self):
        self.assertEqual(iptv.parse(LIST)[2]["opts"], ["#EXTVLCOPT:http-referrer=http://ref.example/", "#EXTVLCOPT:http-user-agent=Custom/1"])

    def test_options_do_not_leak_to_the_next_channel(self):
        self.assertEqual(iptv.parse(LIST + "#EXTINF:-1,C\nhttp://c/1\n")[3]["opts"], [])

    def test_not_a_playlist(self):
        self.assertEqual(iptv.parse("<html>nope</html>"), [])

    def test_byte_order_mark_is_accepted(self):
        self.assertEqual(len(iptv.parse("﻿" + LIST)), 3)

    def test_non_http_sources_are_skipped(self):
        self.assertEqual(iptv.parse("#EXTM3U\n#EXTINF:-1,X\nrtp://239.0.0.1:1234\n"), [])

    def test_header_keeps_the_guide_address(self):
        self.assertEqual(iptv.header(LIST), ' x-tvg-url="http://example.org/e.xml"')
        self.assertEqual(iptv.header("#EXTM3U\n"), "")


class Public(unittest.TestCase):
    def test_public_address_passes(self):
        self.assertTrue(iptv.is_public("https://example.org/a.m3u8", public))

    def test_only_http_and_https(self):
        for url in ("file:///etc/passwd", "ftp://example.org/a", "gopher://x/"):
            self.assertFalse(iptv.is_public(url, public), url)

    def test_private_targets_are_refused(self):
        for ip in ("127.0.0.1", "192.168.1.14", "10.0.0.1", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"):
            self.assertFalse(iptv.is_public("http://name.example/", lambda h: {ip}), ip)

    def test_one_private_address_among_several_is_refused(self):
        self.assertFalse(iptv.is_public("http://x.example/", lambda h: {"8.8.8.8", "127.0.0.1"}))

    def test_unresolvable_is_refused(self):
        def fail(host):
            raise OSError("no such host")
        self.assertFalse(iptv.is_public("http://x.example/", fail))

    def test_no_host_is_refused(self):
        self.assertFalse(iptv.is_public("http:///a", public))


class Probe(unittest.TestCase):
    PL = "http://x/l.m3u8"

    def test_fast_segment_is_online(self):
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: (MEDIA, .1), "http://x/s3.ts": (VIDEO, 4.0)})), "online")

    def test_uses_a_segment_three_from_the_end(self):
        f = fetcher({self.PL: (MEDIA, .1), "http://x/s3.ts": (VIDEO, 1.0)})
        iptv.probe(self.PL, f)
        self.assertEqual(f.calls[-1][0], "http://x/s3.ts")

    def test_short_playlist_uses_its_first_segment(self):
        short = "#EXTM3U\n#EXTINF:6.0,\na.ts\n"
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: (short, .1), "http://x/a.ts": (VIDEO, 1.0)})), "online")

    def test_just_under_the_margin_is_lag(self):
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: (MEDIA, .1), "http://x/s3.ts": (VIDEO, 4.1)})), "lag")

    def test_tag_after_the_duration_is_not_a_segment(self):
        text = "#EXTM3U\n#EXTINF:6.0,\n#EXT-X-BYTERANGE:1000@0\nseg.ts\n"
        f = fetcher({self.PL: (text, .1), "http://x/seg.ts": (VIDEO, 1.0)})
        self.assertEqual(iptv.probe(self.PL, f), "online")
        self.assertEqual(f.calls[-1][0], "http://x/seg.ts")

    def test_master_playlist_follows_the_first_variant(self):
        f = fetcher({"http://x/m.m3u8": (MASTER, .1), "http://x/variant/index.m3u8": (MEDIA, .1),
                     "http://x/variant/s3.ts": (VIDEO, 1.0)})
        self.assertEqual(iptv.probe("http://x/m.m3u8", f), "online")

    def test_empty_answer_is_offline(self):
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: (MEDIA, .1), "http://x/s3.ts": (b"", .01)})), "offline")

    def test_web_page_instead_of_video_is_offline(self):
        page = b"<html>" + b"blocked in your country" * 200
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: (MEDIA, .1), "http://x/s3.ts": (page, .01)})), "offline")

    def test_only_the_start_of_a_segment_is_kept(self):
        kept = []

        def fetch(url, limit, timeout, keep=None, headers=None):
            kept.append(keep)
            return (MEDIA.encode() if url == self.PL else VIDEO[:keep]), .1, url
        iptv.probe(self.PL, fetch)
        self.assertLessEqual(kept[-1], 16384)

    def test_channel_options_become_request_headers(self):
        f = fetcher({self.PL: (MEDIA, .1), "http://x/s3.ts": (VIDEO, 1.0)})
        iptv.probe(self.PL, f, ["#EXTVLCOPT:http-referrer=http://r/", "#EXTVLCOPT:http-user-agent=UA/1"])
        self.assertEqual(f.calls[-1][1], {"Referer": "http://r/", "User-Agent": "UA/1"})

    def test_dead_host_is_offline(self):
        self.assertEqual(iptv.probe(self.PL, fetcher({})), "offline")

    def test_dead_segment_is_offline(self):
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: (MEDIA, .1)})), "offline")

    def test_response_that_is_not_hls_is_offline(self):
        self.assertEqual(iptv.probe(self.PL, fetcher({self.PL: ("<html>", .1)})), "offline")


class Results(unittest.TestCase):
    ROWS = [row("a"), row("b", "lag"), row("c", "offline")]

    def test_counts(self):
        self.assertEqual(iptv.counts(self.ROWS), {"online": 1, "lag": 1, "offline": 1, "total": 3})

    def test_duplicates_count_once(self):
        self.assertEqual(iptv.counts([row("a"), row("a")])["total"], 1)

    def test_clean_playlist_has_only_fast_channels(self):
        self.assertEqual(iptv.clean(self.ROWS), "#EXTM3U\n#EXTINF:-1,a\nhttp://a/1\n")

    def test_clean_playlist_keeps_options_and_guide(self):
        r = {**row("a"), "opts": ["#EXTVLCOPT:http-referrer=http://r/"]}
        self.assertEqual(iptv.clean([r], ' x-tvg-url="u"'), '#EXTM3U x-tvg-url="u"\n#EXTINF:-1,a\n#EXTVLCOPT:http-referrer=http://r/\nhttp://a/1\n')

    def test_same_url_in_two_lists_is_kept_once(self):
        self.assertEqual(iptv.clean([row("a"), row("a")]).count("http://a/1"), 1)

    def test_too_few_channels_is_not_a_usable_playlist(self):
        self.assertFalse(iptv.usable([row(i) for i in range(iptv.MIN_CHANNELS - 1)]))
        self.assertTrue(iptv.usable([row(i) for i in range(iptv.MIN_CHANNELS)]))

    def test_duplicates_do_not_reach_the_floor(self):
        self.assertFalse(iptv.usable([row("a")] * iptv.MIN_CHANNELS))


class Lists(unittest.TestCase):
    def test_name_defaults_to_the_file_in_the_address(self):
        self.assertEqual(iptv.new_list("url", "", "https://x/iptv/cn%20all.m3u8")["name"], "cn all.m3u8")

    def test_ids_differ_for_the_same_source(self):
        self.assertNotEqual(iptv.new_list("url", "a", "https://x/1")["id"], iptv.new_list("url", "a", "https://x/1")["id"])

    def test_address_must_be_http(self):
        self.assertTrue(iptv.valid_address("https://x/a.m3u8"))
        self.assertFalse(iptv.valid_address("file:///etc/passwd"))
        self.assertFalse(iptv.valid_address("x" * 3000))

    def test_view_hides_channels_and_counts_them(self):
        l = {**iptv.new_list("url", "n", "https://x/1"), "rows": [row("a"), row("b", "lag")]}
        v = iptv.view(l)
        self.assertNotIn("rows", v)
        self.assertEqual((v["counts"]["online"], v["counts"]["lag"]), (1, 1))

    def test_channels_show_name_group_and_state(self):
        l = {"rows": [{**row("x"), "info": '#EXTINF:-1 group-title="News",Channel A'}]}
        self.assertEqual(iptv.channels(l), [{"name": "Channel A", "group": "News", "state": "online", "url": "http://x/1"}])


class Check(unittest.TestCase):
    PAGES = {"http://a/l": (MEDIA, .1), "http://a/s3.ts": (VIDEO, 1.0)}
    TEXT = "#EXTM3U\n#EXTINF:-1,A\nhttp://a/l\n"

    def lst(self, i, **over):
        return {"id": i, "name": i, "kind": "url", "url": f"http://{i}", "rows": [], "checked": 0, "error": "", **over}

    def test_states_are_filled_in(self):
        lists, complete = iptv.check_lists([self.lst("one")], lambda l: self.TEXT, fetcher(self.PAGES), 100)
        self.assertTrue(complete)
        self.assertEqual(lists[0]["rows"][0]["state"], "online")
        self.assertEqual((lists[0]["checked"], lists[0]["error"]), (100, ""))

    def test_a_failed_list_keeps_its_channels(self):
        def read(l):
            raise OSError("down")
        old = [row("a")]
        lists, complete = iptv.check_lists([self.lst("one", rows=old, checked=5)], read, fetcher({}), 100)
        self.assertFalse(complete)
        self.assertEqual((lists[0]["rows"], lists[0]["checked"]), (old, 5))
        self.assertTrue(lists[0]["error"])

    def test_a_list_with_no_channels_counts_as_failed(self):
        lists, complete = iptv.check_lists([self.lst("one", rows=[row("a")])], lambda l: "<html>", fetcher({}), 100)
        self.assertFalse(complete)
        self.assertEqual(len(lists[0]["rows"]), 1)

    def test_a_channel_in_two_lists_is_probed_once(self):
        f = fetcher(self.PAGES)
        iptv.check_lists([self.lst("one"), self.lst("two")], lambda l: self.TEXT, f, 100)
        self.assertEqual(sum(1 for u, _ in f.calls if u == "http://a/l"), 1)


if __name__ == "__main__":
    unittest.main()
