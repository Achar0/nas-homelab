import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arrivals  # noqa: E402
import attention  # noqa: E402
import guest  # noqa: E402

NOW = 1_800_000_000
HEALTHY_PROM = {"md_active": 2, "md_required": 2, "smart_status": {"sda": 1}, "drive_temp": {"sda": 35},
                "free_ratio": 0.5, "free_bytes": 3.2e12, "speed_last": 900e6, "speed_median": 930e6}


def inputs(**over):
    base = {"netwatch": None, "kuma": {"AdGuard": 1}, "prom": dict(HEALTHY_PROM), "restarts": {}, "ab_missing": None}
    return {**base, **over}


def prom(**over):
    return {**HEALTHY_PROM, **over}


def status(data):
    return guest.status(data, NOW, NOW)


class Status(unittest.TestCase):
    def test_all_fine(self):
        self.assertEqual(status(inputs()), {"state": "ok", "title": "Everything's running", "detail": "All services are online"})

    def test_named_service_down_uses_its_plain_name(self):
        s = status(inputs(kuma={"AdGuard": 0}))
        self.assertEqual((s["state"], s["title"]), ("warn", "Ad blocking is down"))

    def test_plain_names_ignore_case(self):
        self.assertEqual(status(inputs(kuma={"adguard home": 0}))["title"], "Ad blocking is down")

    def test_real_monitor_names(self):
        self.assertEqual(status(inputs(kuma={"Theater": 0}))["title"], "The media library is down")
        self.assertEqual(status(inputs(kuma={"Homepage": 0}))["title"], "The home page is down")

    def test_unmapped_service_stays_anonymous(self):
        s = status(inputs(kuma={"Secret Thing": 0}))
        self.assertEqual(s["title"], "A service is down")
        self.assertNotIn("Secret", json.dumps(s))

    def test_storage_problems(self):
        for bad in (prom(md_active=1), prom(smart_status={"sda": 0}), prom(drive_temp={"sda": 51}), prom(free_ratio=0.1)):
            self.assertEqual(status(inputs(prom=bad))["title"], "Storage needs attention", bad)

    def test_storage_words_never_name_a_drive(self):
        self.assertNotIn("sda", json.dumps(status(inputs(prom=prom(smart_status={"sda": 0})))))

    def test_restart_loop_hides_the_container_name(self):
        s = status(inputs(restarts={"mc-collector": 3}))
        self.assertEqual(s["title"], "Something isn't working right now")
        self.assertNotIn("collector", json.dumps(s))

    def test_two_restarts_are_not_a_problem(self):
        self.assertEqual(status(inputs(restarts={"x": 2}))["state"], "ok")

    def test_slow_internet(self):
        self.assertEqual(status(inputs(prom=prom(speed_last=100e6)))["title"], "Internet is slow right now")

    def test_most_serious_first_then_a_count(self):
        s = status(inputs(prom=prom(md_active=1, speed_last=100e6), kuma={"AdGuard": 0}))
        self.assertEqual((s["title"], s["detail"]), ("Storage needs attention", "and 2 more"))

    def test_failing_storage_beats_a_service_but_low_space_does_not(self):
        self.assertEqual(status(inputs(prom=prom(free_ratio=0.1), kuma={"AdGuard": 0}))["title"], "Ad blocking is down")

    def test_unreadable_source_is_unknown_never_all_online(self):
        for key in ("kuma", "prom", "restarts"):
            s = status(inputs(**{key: None}))
            self.assertEqual((s["state"], s["title"]), ("unknown", "Status unavailable"), key)

    def test_known_problem_beats_unknown(self):
        s = status(inputs(prom=None, kuma={"AdGuard": 0}))
        self.assertEqual(s["title"], "Ad blocking is down")

    def test_prometheus_without_its_exporters_is_unknown(self):
        for over in ({"free_ratio": None}, {"md_active": None}):
            self.assertEqual(status(inputs(prom=prom(**over)))["title"], "Status unavailable", over)

    def test_any_missing_exporter_is_unknown(self):
        for over in ({"smart_status": {}}, {"drive_temp": {}}, {"speed_last": None}):
            self.assertEqual(status(inputs(prom=prom(**over)))["title"], "Status unavailable", over)

    def test_kuma_with_no_monitors_is_unknown(self):
        self.assertEqual(status(inputs(kuma={}))["title"], "Status unavailable")

    def test_no_data_yet_is_unknown(self):
        self.assertEqual(guest.status(None, NOW, 0)["title"], "Status unavailable")

    def test_stale_data_is_unknown(self):
        self.assertEqual(guest.status(inputs(), NOW, NOW - 301)["title"], "Status unavailable")
        self.assertEqual(guest.status(inputs(), NOW, NOW - 300)["title"], "Everything's running")

    def test_intrusions_never_reach_guests(self):
        nw = {"items": [{"ip": "203.0.113.7", "live": True, "flag": ["On blocklist"], "scope": "internet", "dir": "in", "last": NOW}]}
        s = status(inputs(netwatch=nw))
        self.assertEqual(s["title"], "Everything's running")
        self.assertNotIn("203.0.113.7", json.dumps(s))

    def test_a_dismissal_does_not_hide_a_live_problem(self):
        # guest.status takes no incident state at all: dismissing an alert can't reach it
        self.assertEqual(status(inputs(kuma={"AdGuard": 0}))["state"], "warn")

    def test_demo_statuses_cover_each_kind(self):
        self.assertEqual(guest.DEMO["down"]["title"], "Ad blocking is down")
        self.assertEqual(guest.DEMO["storage"]["title"], "Storage needs attention")
        self.assertEqual(guest.DEMO["restart"]["title"], "Something isn't working right now")
        self.assertEqual(guest.DEMO["slow"]["title"], "Internet is slow right now")
        self.assertEqual(guest.DEMO["many"]["detail"], "and 2 more")
        self.assertEqual(guest.DEMO["unknown"]["title"], "Status unavailable")


def torrent(name, progress=1.0, path="", completed=NOW - 100, state="downloading"):
    return {"name": name, "progress": progress, "content_path": path, "completion_on": completed, "state": state, "eta": 60}


class Downloads(unittest.TestCase):
    def build(self, *torrents):
        return guest.downloads(arrivals.build(list(torrents), NOW))

    def test_release_name_is_only_counted(self):
        d = self.build(torrent("Some.Movie.2024.1080p.x265-GRP"), torrent("Other.Thing.2023.WEB", progress=0.5))
        self.assertEqual((d["arrived"], d["downloading"], d["other"]), ([], [], 2))
        self.assertNotIn("Some.Movie", json.dumps(d))

    def test_recognised_episode_keeps_its_name(self):
        d = self.build(torrent("[Group] Example Show - 05 [1080p].mkv"))
        self.assertEqual((d["arrived"][0]["show"], d["arrived"][0]["ep"], d["other"]), ("Example Show", "E05", 0))

    def test_renamed_path_counts_as_recognised(self):
        d = self.build(torrent("whatever", path="/media/x/Sample Series S01E10.mkv", progress=0.62))
        self.assertEqual(d["downloading"][0]["show"], "Sample Series")

    def test_a_year_is_not_an_episode_number(self):
        d = self.build(torrent("[GRP] Private Film - 2024 [1080p]"))
        self.assertEqual((d["arrived"], d["other"]), ([], 1))
        self.assertNotIn("Private", json.dumps(d))

    def test_long_running_shows_keep_their_name(self):
        self.assertEqual(self.build(torrent("[G] Example Show - 1120 [1080p].mkv"))["arrived"][0]["ep"], "E1120")

    def test_old_finished_unknowns_are_not_counted(self):
        self.assertEqual(self.build(torrent("Some.Movie.2024", completed=NOW - 90 * 86400))["other"], 0)

    def test_known_flag_is_removed_for_guests(self):
        self.assertNotIn("known", json.dumps(self.build(torrent("[G] Example Show - 05.mkv"))))


class Summary(unittest.TestCase):
    def test_numbers_and_parts(self):
        s = guest.summary(inputs(), {"arrived": [], "downloading": []}, NOW, NOW)
        self.assertEqual((s["internet_bps"], s["free_bytes"]), (900e6, 3.2e12))
        self.assertEqual(s["status"]["state"], "ok")
        self.assertEqual(s["downloads"]["other"], 0)

    def test_numbers_are_null_without_prometheus(self):
        s = guest.summary(inputs(prom=None), {"arrived": [], "downloading": []}, NOW, NOW)
        self.assertEqual((s["internet_bps"], s["free_bytes"]), (None, None))

    def test_no_inputs_at_all(self):
        s = guest.summary(None, {"arrived": [], "downloading": []}, NOW, 0)
        self.assertEqual(s["status"]["title"], "Status unavailable")


class FollowsTheRules(unittest.TestCase):
    def test_guest_status_uses_the_same_rule(self):
        inputs = {"kuma": {"AdGuard": 1}, "restarts": {},
                  "prom": {"md_active": 2, "md_required": 2, "smart_status": {"sda": 1}, "drive_temp": {"sda": 40},
                           "free_ratio": 0.18, "speed_last": 900e6, "speed_median": 920e6}}
        rules = {**attention.DEFAULT_RULES, "free_pct": 20}
        self.assertEqual(guest.status(inputs, 100, 100)["state"], "ok")
        self.assertEqual(guest.status(inputs, 100, 100, rules)["title"], "Storage needs attention")
        self.assertEqual(guest.summary(inputs, {}, 100, 100, rules)["status"]["title"], "Storage needs attention")



EMPTY = {"arrived": [], "downloading": []}


class Tv(unittest.TestCase):
    def test_tv_hides_status_unless_something_is_wrong(self):
        self.assertIsNone(guest.tv(inputs(), EMPTY, None, NOW, NOW)["status"])
        self.assertIsNone(guest.tv(None, EMPTY, None, NOW, NOW)["status"])  # unknown, first boot

    def test_tv_status_is_bilingual(self):
        s = guest.tv(inputs(kuma={"AdGuard": 0}), EMPTY, None, NOW, NOW)["status"]
        self.assertEqual(s, {"zh": "广告拦截暂时不可用", "en": "Ad blocking is down"})

    def test_every_status_title_has_chinese(self):
        titles = [guest.STORAGE, guest.BROKEN, guest.SLOW] + [p + " is down" for _, p in guest.PLAIN_NAMES] + ["A service is down"]
        for title in titles:
            self.assertNotEqual(guest.tv_line(title)["zh"], title)

    def test_tv_episodes_known_only_three_at_most_arrived_first(self):
        data = {"arrived": [{"show": f"Show {i}", "ep": "E01", "at": NOW, "known": True} for i in range(2)]
                + [{"show": "Some.Movie", "ep": "", "at": NOW, "known": False}],
                "downloading": [{"show": f"Next {i}", "ep": "E02", "progress": .5, "eta": 9, "stalled": False, "known": True} for i in range(2)]}
        eps = guest.tv(inputs(), data, None, NOW, NOW)["episodes"]
        self.assertEqual([e["show"] for e in eps], ["Show 0", "Show 1", "Next 0"])
        self.assertEqual(eps[0]["at"], NOW)
        self.assertIsNone(eps[2]["at"])

    def test_tv_drops_stale_weather(self):
        self.assertIsNone(guest.tv(inputs(), EMPTY, {"fetched": NOW - 3 * 3600 - 1}, NOW, NOW)["weather"])

    def test_tv_keeps_fresh_weather(self):
        w = {"fetched": NOW - 60}
        self.assertEqual(guest.tv(inputs(), EMPTY, w, NOW, NOW)["weather"], w)


if __name__ == "__main__":
    unittest.main()
