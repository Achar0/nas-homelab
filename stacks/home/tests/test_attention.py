import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import attention  # noqa: E402

NOW = 1_800_000_000
EMPTY = {"netwatch": None, "kuma": None, "prom": None, "restarts": None, "ab_missing": None}


def run(inputs, state=None, now=NOW, rules=attention.DEFAULT_RULES):
    state = {} if state is None else state
    items, urgent, pushes = attention.evaluate({**EMPTY, **inputs}, state, now, rules)
    return items, urgent, pushes, state


def nw_item(ip, first, flag, direction="in", live=True, last=None):
    return {"ip": ip, "scope": "internet", "first": first, "last": last or NOW, "live": live,
            "flag": flag, "dir": direction, "services": ["SSH"], "geo": {"city": "X", "country": "NL"}}


def nw(*items):
    return {"items": list(items)}


PROM_OK = {"md_active": 2, "md_required": 2, "smart_status": {"sda": 1, "sdb": 1}, "drive_temp": {"sda": 40},
           "free_ratio": 0.7, "speed_last": 900e6, "speed_median": 920e6}


def by_id(items, prefix):
    hits = [i for i in items if i["id"].startswith(prefix)]
    assert len(hits) == 1, (prefix, items)
    return hits[0]


class Intrusion(unittest.TestCase):
    def test_intrusion_needs_3_minutes(self):
        state = {}
        attack = {"netwatch": nw(nw_item("203.0.113.7", NOW - 5 * 3600, ["Inbound from the internet to SSH"]))}
        items, urgent, pushes, _ = run(attack, state, NOW)        # old Netwatch 'first' must not count
        self.assertEqual(by_id(items, "intrusion:").get("level"), "normal")
        self.assertIsNone(urgent)
        self.assertEqual(pushes, [])
        run(attack, state, NOW + 120)
        items, urgent, pushes, _ = run(attack, state, NOW + 190)
        self.assertEqual(by_id(items, "intrusion:")["level"], "urgent")
        self.assertEqual(urgent["id"], "intrusion:203.0.113.7")
        self.assertEqual(len(pushes), 1)

    def test_single_sighting_never_escalates(self):
        state = {}
        once = {"netwatch": nw(nw_item("203.0.113.7", NOW, ["Inbound from the internet to SSH"]))}
        gone = {"netwatch": nw(nw_item("203.0.113.7", NOW, ["Inbound from the internet to SSH"], live=False, last=NOW))}
        run(once, state, NOW)
        for t in (60, 120, 180, 240):
            items, urgent, pushes, _ = run(gone, state, NOW + t)
            self.assertIsNone(urgent, t)
            self.assertEqual(pushes, [], t)
            self.assertEqual(by_id(items, "intrusion:")["level"], "normal")

    def test_outgoing_flag_is_normal(self):
        items, urgent, _, _ = run({"netwatch": nw(nw_item("198.51.100.9", NOW - 3600, ["On blocklist.de"], direction="out"))})
        self.assertEqual(by_id(items, "flagged-out:")["level"], "normal")
        self.assertIsNone(urgent)

    def test_old_netwatch_entry_not_active(self):
        old = nw_item("203.0.113.7", NOW - 7200, ["Inbound from the internet to SSH"], live=False, last=NOW - 3000)
        items, _, _, _ = run({"netwatch": nw(old)})
        self.assertEqual(items, [])


class Kuma(unittest.TestCase):
    def test_kuma_down_2_minutes_urgent(self):
        state = {}
        items, urgent, _, _ = run({"kuma": {"AdGuard": 0}}, state, NOW)
        self.assertEqual(by_id(items, "kuma-down:AdGuard")["level"], "normal")
        self.assertIsNone(urgent)
        items, urgent, pushes, _ = run({"kuma": {"AdGuard": 0}}, state, NOW + 130)
        self.assertEqual(by_id(items, "kuma-down:AdGuard")["level"], "urgent")
        self.assertEqual(urgent["id"], "kuma-down:AdGuard")
        self.assertEqual(len(pushes), 1)

    def test_kuma_recovered_is_normal_resolved(self):
        state = {}
        run({"kuma": {"AdGuard": 0}}, state, NOW)
        items, urgent, _, _ = run({"kuma": {"AdGuard": 1}}, state, NOW + 40)
        it = by_id(items, "kuma-down:AdGuard")
        self.assertTrue(it["resolved"])
        self.assertEqual(it["level"], "normal")
        self.assertIsNone(urgent)


class Prom(unittest.TestCase):
    def test_raid_degraded_urgent(self):
        items, urgent, _, _ = run({"prom": {**PROM_OK, "md_active": 1}})
        self.assertEqual(urgent["id"], "raid")

    def test_smart_fail_urgent(self):
        _, urgent, _, _ = run({"prom": {**PROM_OK, "smart_status": {"sda": 0, "sdb": 1}}})
        self.assertEqual(urgent["id"], "smart:sda")

    def test_free_space_low_normal(self):
        items, urgent, _, _ = run({"prom": {**PROM_OK, "free_ratio": 0.1}})
        self.assertEqual(by_id(items, "space")["level"], "normal")
        self.assertIsNone(urgent)

    def test_slow_speedtest_normal(self):
        items, _, _, _ = run({"prom": {**PROM_OK, "speed_last": 300e6}})
        self.assertEqual(by_id(items, "speed")["level"], "normal")

    def test_hot_drive_normal(self):
        items, _, _, _ = run({"prom": {**PROM_OK, "drive_temp": {"sda": 53}}})
        self.assertEqual(by_id(items, "hot:sda")["level"], "normal")

    def test_all_fine_is_quiet(self):
        items, urgent, pushes, _ = run({"prom": PROM_OK, "kuma": {"AdGuard": 1}, "netwatch": nw(), "restarts": {}, "ab_missing": []})
        self.assertEqual((items, urgent, pushes), ([], None, []))


class Other(unittest.TestCase):
    def test_restart_loop_urgent(self):
        _, urgent, _, _ = run({"restarts": {"adguardhome": 3, "glances": 1}})
        self.assertEqual(urgent["id"], "restarts:adguardhome")

    def test_ab_missing_normal(self):
        items, _, _, _ = run({"ab_missing": [{"show": "Frieren", "episode": "S02E06", "seen_at": NOW - 7 * 3600}]})
        self.assertEqual(by_id(items, "missing:Frieren S02E06")["level"], "normal")


class Lifecycle(unittest.TestCase):
    def test_auto_resolve_kept_24h(self):
        state = {}
        run({"prom": {**PROM_OK, "free_ratio": 0.1}}, state, NOW)
        items, _, _, _ = run({"prom": PROM_OK}, state, NOW + 60)
        self.assertTrue(by_id(items, "space")["resolved"])
        items, _, _, _ = run({"prom": PROM_OK}, state, NOW + 23 * 3600)
        self.assertTrue(by_id(items, "space")["resolved"])
        items, _, _, _ = run({"prom": PROM_OK}, state, NOW + 25 * 3600)
        self.assertEqual(items, [])

    def test_push_once_per_incident(self):
        state = {}
        bad = {"prom": {**PROM_OK, "md_active": 1}}
        _, _, p1, _ = run(bad, state, NOW)
        _, _, p2, _ = run(bad, state, NOW + 30)
        _, _, p3, _ = run(bad, state, NOW + 60)
        self.assertEqual((len(p1), len(p2), len(p3)), (1, 0, 0))

    def test_reoccurrence_alerts_again(self):
        state = {}
        bad, good = {"prom": {**PROM_OK, "md_active": 1}}, {"prom": PROM_OK}
        run(bad, state, NOW)
        attention.ack(state, "raid")
        _, urgent, _, _ = run(good, state, NOW + 60)
        self.assertIsNone(urgent)
        _, urgent, pushes, _ = run(bad, state, NOW + 120)
        self.assertEqual(urgent["id"], "raid")       # the takeover comes back at once
        self.assertEqual(pushes, [])                 # but the phone isn't buzzed again within the hour
        run(good, state, NOW + 180)
        _, urgent, pushes, _ = run(bad, state, NOW + 2 * 3600)
        self.assertEqual(urgent["id"], "raid")
        self.assertEqual(len(pushes), 1)             # an hour later it pushes again

    def test_dismissed_hidden(self):
        state = {}
        run({"prom": {**PROM_OK, "free_ratio": 0.1}}, state, NOW)
        self.assertTrue(attention.dismiss(state, "space"))
        items, _, _, _ = run({"prom": {**PROM_OK, "free_ratio": 0.1}}, state, NOW + 30)
        self.assertEqual(items, [])
        self.assertFalse(attention.dismiss(state, "no-such-id"))

    def test_acked_urgent_not_shown_as_takeover(self):
        state = {}
        run({"prom": {**PROM_OK, "md_active": 1}}, state, NOW)
        self.assertTrue(attention.ack(state, "raid"))
        items, urgent, _, _ = run({"prom": {**PROM_OK, "md_active": 1}}, state, NOW + 30)
        self.assertIsNone(urgent)
        self.assertEqual(by_id(items, "raid")["level"], "urgent")   # still pinned until it resolves

    def test_dismissed_then_escalates_shows_takeover(self):
        state = {}
        run({"kuma": {"AdGuard": 0}}, state, NOW)
        attention.dismiss(state, "kuma-down:AdGuard")
        items, urgent, pushes, _ = run({"kuma": {"AdGuard": 0}}, state, NOW + 130)
        self.assertEqual(urgent["id"], "kuma-down:AdGuard")
        self.assertEqual(len(pushes), 1)

    def test_flapping_pushes_once_per_hour(self):
        state, sent = {}, 0
        t = NOW
        for _ in range(5):          # down 2.5 min, up 30 s, repeat
            run({"kuma": {"AdGuard": 0}}, state, t)
            _, _, p, _ = run({"kuma": {"AdGuard": 0}}, state, t + 150)
            sent += len(p)
            run({"kuma": {"AdGuard": 1}}, state, t + 160)
            t += 180
        self.assertEqual(sent, 1)

    def test_global_push_cap(self):
        state = {}
        many = {"restarts": {f"c{i}": 5 for i in range(15)}}
        _, _, pushes, _ = run(many, state, NOW)
        self.assertEqual(len(pushes), attention.PUSH_CAP_PER_HOUR)

    def test_missing_source_skipped(self):
        state = {}
        run({"prom": {**PROM_OK, "free_ratio": 0.1}}, state, NOW)
        items, _, _, _ = run({"prom": None, "kuma": None}, state, NOW + 30)
        self.assertFalse(by_id(items, "space")["resolved"])   # unknown, not "fixed"

    def test_priority_order_and_acked_flag(self):
        state = {}
        inputs = {"prom": {**PROM_OK, "free_ratio": 0.1, "md_active": 1, "smart_status": {"sda": 0, "sdb": 1}}}
        run(inputs, state, NOW)
        attention.ack(state, "raid")
        items, urgent, _, _ = run(inputs, state, NOW + 30)
        self.assertEqual([i["id"] for i in items], ["smart:sda", "raid", "space"])   # urgent, urgent acked, normal
        self.assertEqual([i["acked"] for i in items], [False, True, False])
        self.assertEqual(urgent["id"], "smart:sda")

    def test_urgent_sorted_first(self):
        items, _, _, _ = run({"prom": {**PROM_OK, "free_ratio": 0.1, "md_active": 1}})
        self.assertEqual(items[0]["id"], "raid")


class FollowsTheRules(unittest.TestCase):
    def rules(self, **kw):
        return {**attention.DEFAULT_RULES, **kw}

    def ids(self, inputs, **kw):
        active, _ = attention.conditions({**EMPTY, **inputs}, NOW, self.rules(**kw))
        return set(active)

    def test_defaults_are_todays_numbers(self):
        self.assertEqual(attention.DEFAULT_RULES, {"free_pct": 15, "service_down_min": 2, "intrusion_min": 3, "hot_c": 50, "slow_pct": 50})

    def test_free_space_follows_rule(self):
        p = {"prom": {**PROM_OK, "free_ratio": 0.18}}
        self.assertNotIn("space", self.ids(p, free_pct=15))
        self.assertIn("space", self.ids(p, free_pct=20))

    def test_hot_follows_rule(self):
        p = {"prom": {**PROM_OK, "drive_temp": {"sda": 55}}}
        self.assertIn("hot:sda", self.ids(p, hot_c=50))
        self.assertNotIn("hot:sda", self.ids(p, hot_c=60))

    def test_slow_follows_rule(self):
        p = {"prom": {**PROM_OK, "speed_last": 600e6, "speed_median": 1000e6}}
        self.assertNotIn("speed", self.ids(p, slow_pct=50))
        self.assertIn("speed", self.ids(p, slow_pct=70))

    def urgent_after(self, inputs, seconds, **kw):
        state = {}
        run(inputs, state, NOW, self.rules(**kw))
        _, urgent, _, _ = run(inputs, state, NOW + seconds, self.rules(**kw))
        return urgent

    def test_service_down_urgent_after_follows_rule(self):
        down = {"kuma": {"AdGuard": 0}}
        self.assertIsNone(self.urgent_after(down, 60, service_down_min=2))
        self.assertIsNotNone(self.urgent_after(down, 60, service_down_min=1))

    def test_intrusion_urgent_after_follows_rule(self):
        attack = {"netwatch": nw(nw_item("203.0.113.7", NOW, ["Inbound from the internet to SSH"]))}
        self.assertIsNone(self.urgent_after(attack, 60, intrusion_min=3))
        self.assertIsNotNone(self.urgent_after(attack, 60, intrusion_min=1))



if __name__ == "__main__":
    unittest.main()
