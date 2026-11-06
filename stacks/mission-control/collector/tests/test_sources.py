import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collector  # noqa: E402
import sources  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


def value(metrics, metric, **labels):
    hits = [v for n, l, v in metrics if n == metric and all(l.get(k) == x for k, x in labels.items())]
    assert len(hits) == 1, (metric, labels, hits)
    return hits[0]


def stats(cpu_total, pre_total, sys_now, sys_pre, cpus, usage, inactive):
    return {"name": "/adguardhome",
            "cpu_stats": {"cpu_usage": {"total_usage": cpu_total}, "system_cpu_usage": sys_now, "online_cpus": cpus},
            "precpu_stats": {"cpu_usage": {"total_usage": pre_total}, "system_cpu_usage": sys_pre},
            "memory_stats": {"usage": usage, "stats": {"inactive_file": inactive}}}


class Docker(unittest.TestCase):
    containers = [{"Id": "abc", "Names": ["/adguardhome"], "State": "running"}]

    def test_docker_cpu_percent(self):
        m = sources.parse_docker(self.containers, {"abc": stats(12e8, 10e8, 44e9, 40e9, 4, 1, 0)})
        self.assertAlmostEqual(value(m, "mc_container_cpu_percent", name="adguardhome"), 5.0)

    def test_docker_memory_minus_cache(self):
        m = sources.parse_docker(self.containers, {"abc": stats(1, 1, 2, 1, 4, 700e6, 100e6)})
        self.assertEqual(value(m, "mc_container_memory_bytes", name="adguardhome"), 600e6)

    def test_docker_real_fixture(self):
        cs = fx("docker_containers.json")
        ag = [c for c in cs if "/adguardhome" in c["Names"]][0]
        m = sources.parse_docker(cs, {ag["Id"]: fx("docker_stats_adguardhome.json")})
        self.assertGreater(value(m, "mc_container_memory_bytes", name="adguardhome"), 50e6)
        self.assertGreaterEqual(value(m, "mc_container_cpu_percent", name="adguardhome"), 0)


class Services(unittest.TestCase):
    def test_qbt(self):
        tr, tor, md = fx("qbt_transfer.json"), fx("qbt_torrents.json"), fx("qbt_maindata.json")
        m = sources.parse_qbt(tr, tor, md)
        self.assertEqual(value(m, "mc_qbt_upload_bytes_per_second"), tr["up_info_speed"])
        self.assertEqual(value(m, "mc_qbt_download_bytes_per_second"), tr["dl_info_speed"])
        seeding = sum(t["state"] in ("uploading", "stalledUP", "queuedUP", "forcedUP") for t in tor)
        self.assertEqual(value(m, "mc_qbt_seeding"), seeding)
        self.assertEqual(value(m, "mc_qbt_uploaded_session_bytes"), tr["up_info_data"])
        self.assertAlmostEqual(value(m, "mc_qbt_ratio"), 0.39)

    def test_adguard(self):
        m = sources.parse_adguard(fx("adguard_stats.json"))
        self.assertEqual(value(m, "mc_adguard_queries_24h"), 81331)
        self.assertEqual(value(m, "mc_adguard_blocked_24h"), 9037)
        self.assertAlmostEqual(value(m, "mc_adguard_latency_seconds"), 0.030715)
        self.assertEqual(value(m, "mc_adguard_top_blocked", domain="otheve.beacon.qq.com"), 1)

    def test_speedtest_units(self):
        m = sources.parse_speedtest(fx("speedtest_latest.json"))
        self.assertEqual(value(m, "mc_speedtest_download_bits_per_second"), 936305472)  # ~936 Mb/s
        self.assertEqual(value(m, "mc_speedtest_upload_bits_per_second"), 512629872)
        self.assertAlmostEqual(value(m, "mc_speedtest_ping_ms"), 4.268)
        self.assertEqual(value(m, "mc_speedtest_last_timestamp_seconds"), 1793984435)  # 2026-11-06T17:00:35Z

    def test_tailscale(self):
        st = {"Self": {"HostName": "nas", "OS": "linux", "Online": True, "LastSeen": "0001-01-01T00:00:00Z"},
              "Peer": {"a": {"HostName": "iphone", "OS": "iOS", "Online": True, "LastSeen": "0001-01-01T00:00:00Z"},
                       "b": {"HostName": "laptop", "OS": "linux", "Online": False, "LastSeen": "2026-11-06T10:00:00Z"}}}
        m = sources.parse_tailscale(st, now=1794000000)
        self.assertEqual(value(m, "mc_tailscale_peers_online"), 2)
        self.assertEqual(value(m, "mc_tailscale_peer_online", name="laptop", os="linux"), 0)
        self.assertEqual(value(m, "mc_tailscale_peer_last_seen_seconds", name="laptop"), 1793959200)
        self.assertEqual(value(m, "mc_tailscale_peer_last_seen_seconds", name="iphone"), 1794000000)

    def test_tailscale_no_peers(self):
        m = sources.parse_tailscale({"Self": fx("tailscale_status.json")["Self"], "Peer": None}, now=1)
        self.assertEqual(value(m, "mc_tailscale_peers_online"), 1)


class Render(unittest.TestCase):
    def test_render_escapes(self):
        out = sources.render([("mc_x", {"d": 'a"b\\c'}, 1), ("mc_x", {"d": "z"}, 2.5)])
        self.assertIn('mc_x{d="a\\"b\\\\c"} 1', out)
        self.assertEqual(out.count("# TYPE mc_x gauge"), 1)

    def test_render_keeps_precision(self):
        out = sources.render([("mc_t", {}, 1793984435), ("mc_r", {}, 0.030715)])
        self.assertIn("mc_t 1793984435\n", out)
        self.assertIn("mc_r 0.030715\n", out)


class DockerFetch(unittest.TestCase):
    def test_one_container_stats_failure_keeps_others(self):
        good = stats(12e8, 10e8, 44e9, 40e9, 4, 700e6, 100e6)
        def fake_get(url, headers=None, opener=None):
            if url.endswith("/containers/json"):
                return [{"Id": "a", "Names": ["/adguardhome"], "State": "running"},
                        {"Id": "gone", "Names": ["/removed"], "State": "running"}]
            if "/containers/gone/" in url:
                raise OSError("404 no such container")
            return good
        orig, collector.get_json = collector.get_json, fake_get
        try:
            m = collector.fetch_docker()
        finally:
            collector.get_json = orig
        self.assertEqual(value(m, "mc_container_memory_bytes", name="adguardhome"), 600e6)
        self.assertFalse([1 for n, l, v in m if l.get("name") == "removed"])


class Collect(unittest.TestCase):
    def test_source_failure_isolated(self):
        def boom():
            raise OSError("down")
        m = collector.collect_all({"qbittorrent": boom, "adguard": lambda: [("mc_adguard_queries_24h", {}, 5)]})
        self.assertEqual(value(m, "mc_up", source="qbittorrent"), 0)
        self.assertEqual(value(m, "mc_up", source="adguard"), 1)
        self.assertEqual(value(m, "mc_adguard_queries_24h"), 5)


if __name__ == "__main__":
    unittest.main()
