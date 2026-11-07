"""Settings file: safe defaults, validation, and never losing the owner's choices."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings  # noqa: E402

FEEDS = [{"name": "Example", "url": "https://example.com/feed.xml", "topic": "tech", "lang": "en"},
         {"name": "Esempio", "url": "https://example.it/rss", "topic": "markets", "lang": "it"}]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "settings.json")
        self.feeds = os.path.join(self.dir, "feeds.json")
        with open(self.feeds, "w") as f:
            json.dump(FEEDS, f)

    def store(self):
        return settings.Store(self.path, self.feeds)

    def write_raw(self, text):
        with open(self.path, "w") as f:
            f.write(text)

    def feed(self, i):
        return {"id": f"id{i}", "name": f"F{i}", "url": f"https://example.com/{i}", "topic": "tech", "lang": "en", "enabled": True}


class Defaults(Base):
    def test_first_run_imports_feeds_json_all_enabled(self):
        feeds = self.store().get()["feeds"]
        self.assertEqual([f["url"] for f in feeds], [f["url"] for f in FEEDS])
        self.assertTrue(all(f["enabled"] for f in feeds))
        self.assertEqual(len({f["id"] for f in feeds}), 2)

    def test_defaults_match_todays_alert_numbers(self):
        self.assertEqual(self.store().get()["alerts"], {"free_pct": 15, "service_down_min": 2, "intrusion_min": 3,
                                                        "hot_c": 50, "slow_pct": 50, "push": True})

    def test_seed_services_in_dock_order(self):
        services = self.store().get()["services"]
        self.assertEqual([s["id"] for s in services],
                         ["home", "mission", "adguard", "qbittorrent", "autobangumi", "speedtest", "kuma", "dockge",
                          "netwatch", "glances", "ugos", "firefox"])
        by = {s["id"]: s for s in services}
        self.assertFalse(by["firefox"]["on_dock"])
        self.assertTrue(by["ugos"]["on_dock"])
        self.assertEqual((by["ugos"]["port"], by["ugos"]["scheme"]), (9443, "https"))
        self.assertEqual(by["autobangumi"]["container"], "autobangumi-7892")
        self.assertEqual(by["firefox"]["container"], "firefox-app-1")

    def test_rail_and_cards(self):
        s = self.store().get()
        self.assertEqual([x["id"] for x in s["rail"]["nas"]], ["cpu", "memory", "temperature", "free"])
        self.assertEqual([x["id"] for x in s["rail"]["services"]], ["qbittorrent", "adguard", "speedtest"])
        self.assertEqual([x["id"] for x in s["cards"]], ["qbittorrent", "adguard", "speedtest", "tailscale", "connections"])

    def test_first_run_has_no_known_containers(self):
        self.assertIsNone(self.store().get()["known_containers"])


class Persistence(Base):
    def test_survives_reload(self):
        self.store().update(lambda s: s["alerts"].update(hot_c=60))
        self.assertEqual(self.store().get()["alerts"]["hot_c"], 60)

    def test_get_returns_a_copy(self):
        st = self.store()
        st.get()["alerts"]["hot_c"] = 99
        self.assertEqual(st.get()["alerts"]["hot_c"], 50)

    def test_fn_returning_false_writes_nothing(self):
        st = self.store()
        st.update(lambda s: False)
        self.assertFalse(os.path.exists(self.path))

    def test_concurrent_updates_lose_nothing(self):
        st = self.store()

        def worker(base):
            for i in range(25):
                st.update(lambda s, n=base + i: s["feeds"].append(self.feed(n)))
        threads = [threading.Thread(target=worker, args=(b * 100,)) for b in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(st.get()["feeds"]), len(FEEDS) + 200)
        self.assertEqual(len(self.store().get()["feeds"]), len(FEEDS) + 200)

    def test_write_failure_keeps_old_value_and_raises_oserror(self):
        st = self.store()
        real = settings.os.replace
        settings.os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        self.addCleanup(setattr, settings.os, "replace", real)
        with self.assertRaises(OSError):
            st.update(lambda s: s["alerts"].update(hot_c=60))
        self.assertEqual(st.get()["alerts"]["hot_c"], 50)


class BrokenFile(Base):
    def assert_kept_aside(self, st, original):
        self.assertTrue(st.problem)
        aside = [f for f in os.listdir(self.dir) if f.startswith("settings.json.bad-")]
        self.assertEqual(len(aside), 1)
        with open(os.path.join(self.dir, aside[0])) as f:
            self.assertEqual(f.read(), original)
        self.assertEqual(st.get()["alerts"]["hot_c"], 50)
        self.assertIsNone(st.get()["known_containers"])

    def test_corrupt_file_is_kept_aside_and_defaults_used(self):
        self.write_raw("{nope")
        self.assert_kept_aside(self.store(), "{nope")

    def test_wrong_value_counts_as_corrupt(self):
        raw = json.dumps({"alerts": {"hot_c": "hot"}})
        self.write_raw(raw)
        self.assert_kept_aside(self.store(), raw)

    def test_not_an_object_counts_as_corrupt(self):
        self.write_raw("[1, 2]")
        self.assert_kept_aside(self.store(), "[1, 2]")

    def test_missing_section_uses_defaults_without_problem(self):
        self.write_raw(json.dumps({"alerts": {"hot_c": 60}}))
        st = self.store()
        self.assertIsNone(st.problem)
        self.assertEqual(st.get()["alerts"]["hot_c"], 60)
        self.assertEqual(st.get()["alerts"]["free_pct"], 15)
        self.assertEqual(len(st.get()["feeds"]), 2)

    def test_still_writable_after_a_broken_file(self):
        self.write_raw("{nope")
        st = self.store()
        st.update(lambda s: s["alerts"].update(hot_c=60))
        self.assertEqual(self.store().get()["alerts"]["hot_c"], 60)


class HandEdits(Base):
    def edit(self, change):
        with open(self.path) as f:
            data = json.load(f)
        change(data)
        with open(self.path, "w") as f:
            json.dump(data, f)
            f.write("\n")   # size changes too, like a real edit

    def test_running_store_sees_a_hand_edit_and_keeps_it(self):
        st = self.store()
        st.update(lambda s: s["alerts"].update(hot_c=60))
        self.edit(lambda d: d["alerts"].update(free_pct=40))
        self.assertEqual(st.get()["alerts"]["free_pct"], 40)
        st.update(lambda s: s["alerts"].update(hot_c=61))
        self.assertEqual(self.store().get()["alerts"]["free_pct"], 40)
        self.assertEqual(self.store().get()["alerts"]["hot_c"], 61)

    def test_update_works_from_the_edited_value(self):
        st = self.store()
        st.update(lambda s: s["alerts"].update(hot_c=60))
        self.edit(lambda d: d["alerts"].update(free_pct=40))
        st.update(lambda s: s["alerts"].update(hot_c=61))   # no get() in between
        self.assertEqual(st.get()["alerts"]["free_pct"], 40)

    def test_bad_hand_edit_on_a_running_store_goes_the_broken_file_path(self):
        st = self.store()
        st.update(lambda s: s["alerts"].update(hot_c=60))
        self.edit(lambda d: d["alerts"].update(hot_c="hot"))
        self.assertEqual(st.get()["alerts"]["hot_c"], 50)
        self.assertTrue(st.problem)
        self.assertEqual(len([f for f in os.listdir(self.dir) if f.startswith("settings.json.bad-")]), 1)

    def test_own_writes_cause_no_reload(self):
        st = self.store()
        st.update(lambda s: s["alerts"].update(hot_c=60))
        load = st._load
        st._load = lambda: self.fail("reloaded its own write")
        self.addCleanup(setattr, st, "_load", load)
        st.get()
        st.update(lambda s: s["alerts"].update(hot_c=61))
        st.get()

    def test_deleted_file_keeps_the_current_values(self):
        st = self.store()
        st.update(lambda s: s["alerts"].update(hot_c=60))
        os.remove(self.path)
        self.assertEqual(st.get()["alerts"]["hot_c"], 60)


class BadStartingList(Base):
    def feeds_file(self, data):
        with open(self.feeds, "w") as f:
            json.dump(data, f)

    def test_bad_entries_are_skipped_and_saving_still_works(self):
        good = FEEDS[0]
        self.feeds_file([good, {"name": "No address"}, {**good, "url": "https://x.example/a", "topic": "sport"},
                         {**good, "url": "ftp://x.example/b"}, "text", {**good}])   # the last repeats the first
        st = self.store()
        self.assertEqual([f["url"] for f in st.get()["feeds"]], [good["url"]])
        st.update(lambda s: s["alerts"].update(hot_c=60))

    def test_not_a_list_gives_no_feeds(self):
        self.feeds_file({"name": "x"})
        self.assertEqual(self.store().get()["feeds"], [])


class Validation(Base):
    def refused(self, fn):
        st = self.store()
        before = st.get()
        with self.assertRaises(ValueError):
            st.update(fn)
        self.assertEqual(st.get(), before)

    def test_out_of_range_update_changes_nothing(self):
        for key, value in (("hot_c", 71), ("hot_c", 39), ("free_pct", 4), ("free_pct", 51), ("service_down_min", 0),
                           ("service_down_min", 61), ("intrusion_min", 0), ("slow_pct", 9), ("slow_pct", 91)):
            self.refused(lambda s, k=key, v=value: s["alerts"].update({k: v}))

    def test_limits_themselves_are_allowed(self):
        st = self.store()
        for key, (low, high) in settings.ALERT_LIMITS.items():
            st.update(lambda s, k=key, v=low: s["alerts"].update({k: v}))
            st.update(lambda s, k=key, v=high: s["alerts"].update({k: v}))

    def test_alert_numbers_must_be_whole_numbers_not_bools(self):
        self.refused(lambda s: s["alerts"].update(hot_c=True))
        self.refused(lambda s: s["alerts"].update(hot_c=50.5))
        self.refused(lambda s: s["alerts"].update(push="yes"))

    def test_feed_values_checked(self):
        for field, value in (("url", "ftp://example.com/x"), ("url", "javascript:alert(1)"), ("topic", "sport"), ("lang", "fr")):
            self.refused(lambda s, f=field, v=value: s["feeds"][0].update({f: v}))

    def test_ports_checked(self):
        for value in (0, 70000, "8080", True, 80.5):
            self.refused(lambda s, v=value: s["services"][0].update(port=v))

    def test_scheme_checked(self):
        self.refused(lambda s: s["services"][0].update(scheme="javascript"))

    def test_on_dock_needs_a_port(self):
        self.refused(lambda s: s["services"][0].update(port=None))

    def test_state_checked(self):
        self.refused(lambda s: s["services"][0].update(state="odd"))
