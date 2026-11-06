import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arrivals  # noqa: E402

NOW = 1_800_000_000


def tor(name, path, done_at=0, progress=1.0, state="stalledUP", eta=8640000, dlspeed=0):
    return {"name": name, "content_path": path, "completion_on": done_at, "progress": progress,
            "state": state, "eta": eta, "dlspeed": dlspeed}


class Parse(unittest.TestCase):
    def test_arrivals_parse_path(self):
        s, e = arrivals.show_episode("x", "/media/番剧/Frieren (2023)/Season 02/Frieren S02E05.mkv")
        self.assertEqual((s, e), ("Frieren", "S02E05"))

    def test_arrivals_fallback_name(self):
        s, e = arrivals.show_episode("[SubGroup] Sample Show Title - 12 [WebRip 1080p HEVC-10bit AAC].mkv", "/x/y.mkv")
        self.assertEqual((s, e), ("Sample Show Title", "E12"))

    def test_batch_name(self):
        s, e = arrivals.show_episode("[Long Series][001-178][GB][WEB-DL][1080P]", "/downloads/[Long Series][001-178][GB][WEB-DL][1080P]")
        self.assertEqual((s, e), ("Long Series", "001-178"))


    def test_group_then_show_batch(self):
        s, e = arrivals.show_episode("[Group][Another_Show][01-13][BIG5][1080p][BDrip][HEVC]", "/downloads/x")
        self.assertEqual((s, e), ("Another Show", "01-13"))

    def test_underscores_become_spaces(self):
        s, _ = arrivals.show_episode("Some_Show_TV+OVA+Extras_dub jpn sub chs (2023-05-13)", "/downloads/x")
        self.assertEqual(s, "Some Show TV+OVA+Extras dub jpn sub chs (2023-05-13)")


class Build(unittest.TestCase):
    def test_arrivals_window_48h(self):
        out = arrivals.build([
            tor("[G] Show A - 03 [1080p].mkv", "/a.mkv", NOW - 3600),
            tor("[G] Show B - 07 [1080p].mkv", "/b.mkv", NOW - 50 * 3600),
            tor("[G] Show C - 01 [1080p].mkv", "/c.mkv", NOW - 60),
        ], NOW)
        self.assertEqual([a["show"] for a in out["arrived"]], ["Show C", "Show A"])

    def test_downloading_progress(self):
        out = arrivals.build([tor("[G] Show D - 02 [1080p].mkv", "/d.mkv", 0, 0.62, "downloading", 240, 5e6)], NOW)
        d = out["downloading"][0]
        self.assertEqual((d["show"], d["ep"], d["progress"], d["eta"], d["stalled"]), ("Show D", "E02", 0.62, 240, False))

    def test_stalled(self):
        out = arrivals.build([tor("[G] Show E - 05 [1080p].mkv", "/e.mkv", 0, 0.3, "stalledDL")], NOW)
        self.assertTrue(out["downloading"][0]["stalled"])
        self.assertIsNone(out["downloading"][0]["eta"])


if __name__ == "__main__":
    unittest.main()
