import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import feeds  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


class Parse(unittest.TestCase):
    def check(self, items, source):
        self.assertEqual(len(items), 2)
        for it in items:
            self.assertTrue(it["title"])
            self.assertNotIn("<", it["summary"])
            self.assertTrue(it["link"].startswith("http"))
            self.assertGreater(it["published"], 1_700_000_000)
            self.assertEqual(it["source"], source)
            self.assertTrue(it["id"])

    def test_parse_rss(self):
        self.check(feeds.parse(fx("rss_sample.xml"), "Il Sole 24 Ore", "tech", "it"), "Il Sole 24 Ore")

    def test_parse_atom(self):
        items = feeds.parse(fx("atom_sample.xml"), "The Verge", "tech", "en")
        self.check(items, "The Verge")
        self.assertEqual(items[0]["lang"], "en")
        self.assertEqual(items[0]["topic"], "tech")

    def test_not_a_feed_raises(self):
        with self.assertRaises(ValueError):
            feeds.parse(fx("broken.html"), "x", "tech", "en")


class Clean(unittest.TestCase):
    def test_html_stripped(self):
        self.assertEqual(feeds.clean("<p>A &amp; B<img src=x></p>"), "A & B")
        self.assertEqual(feeds.clean("<script>alert(1)</script>Hi"), "Hi")

    def test_long_summary_cut(self):
        out = feeds.clean("word " * 300)
        self.assertLessEqual(len(out), 601)
        self.assertTrue(out.endswith("…"))
        self.assertFalse(out[:-1].endswith(" "))


class Dedupe(unittest.TestCase):
    def item(self, title, t, source="A"):
        return {"id": title + source, "title": title, "published": t, "source": source}

    def test_dedupe_same_story(self):
        out = feeds.dedupe([self.item("Apple launches M5 chips", 100, "A"), self.item("Apple launches M5 chip", 50, "B")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "B")  # first published wins

    def test_different_stories_kept(self):
        out = feeds.dedupe([self.item("Apple launches M5 chips", 100), self.item("Borsa di Milano chiude in rialzo", 90)])
        self.assertEqual(len(out), 2)

    def test_same_title_far_apart_kept(self):
        out = feeds.dedupe([self.item("Markets close higher", 0), self.item("Markets close higher", 13 * 3600)])
        self.assertEqual(len(out), 2)


class Balance(unittest.TestCase):
    def test_per_source_cap_newest_first(self):
        items = [{"id": f"a{i}", "source": "Big", "published": i} for i in range(20)] + \
                [{"id": "b0", "source": "Small", "published": 5}]
        out = feeds.balance(items, per_source=8)
        self.assertEqual(sum(1 for x in out if x["source"] == "Big"), 8)
        self.assertEqual(out[0]["published"], 19)
        self.assertIn("b0", [x["id"] for x in out])
        self.assertEqual([x["published"] for x in out], sorted([x["published"] for x in out], reverse=True))


class FetchAll(unittest.TestCase):
    def test_broken_feed_isolated(self):
        cfg = [{"name": "Good", "url": "g", "topic": "tech", "lang": "en"},
               {"name": "Bad", "url": "b", "topic": "tech", "lang": "en"}]

        def fetch(url):
            if url == "b":
                raise OSError("timeout")
            return fx("atom_sample.xml")
        items, errors = feeds.fetch_all(cfg, fetch)
        self.assertEqual(len(items), 2)
        self.assertEqual(errors, ["Bad"])


if __name__ == "__main__":
    unittest.main()
