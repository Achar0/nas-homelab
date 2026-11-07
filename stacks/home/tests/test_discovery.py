"""New containers show up in Settings. Container names here are made up."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import discovery  # noqa: E402
import settings  # noqa: E402


def c(name, ports=(), state="running"):
    return {"Names": [f"/{name}"], "State": state,
            "Ports": [{"IP": ip, "PublicPort": p, "PrivatePort": p, "Type": "tcp"} for ip, p in ports]
                     + [{"PrivatePort": 443, "Type": "tcp"}]}


def scanned(*names):
    cfg = settings.default_settings([])
    discovery.apply(cfg, [c(n) for n in names])
    return cfg


def row(cfg, name):
    return next(s for s in cfg["services"] if s["container"] == name)


class Scan(unittest.TestCase):
    def test_first_scan_only_records_names(self):
        cfg = settings.default_settings([])
        before = len(cfg["services"])
        self.assertTrue(discovery.apply(cfg, [c("exporter-9100"), c("home-3001")]))
        self.assertEqual(cfg["known_containers"], ["exporter-9100", "home-3001"])
        self.assertEqual(len(cfg["services"]), before)

    def test_failed_read_changes_nothing(self):
        for cfg in (settings.default_settings([]), scanned("home-3001")):
            before = repr(cfg)
            self.assertFalse(discovery.apply(cfg, None))
            self.assertEqual(repr(cfg), before)

    def test_nothing_new_reports_no_change(self):
        cfg = scanned("home-3001")
        self.assertFalse(discovery.apply(cfg, [c("home-3001")]))

    def test_new_container_appears_off_the_dock(self):
        cfg = scanned("home-3001")
        self.assertTrue(discovery.apply(cfg, [c("home-3001"), c("photo_vault-8123", [("0.0.0.0", 8123)])]))
        new = row(cfg, "photo_vault-8123")
        self.assertEqual((new["state"], new["on_dock"], new["running"]), ("new", False, True))
        self.assertEqual(new["id"], "c-photo_vault-8123")
        self.assertEqual(new["name"], "Photo Vault")
        self.assertEqual(new["icon"], settings.PLAIN_ICON)
        self.assertIn("photo_vault-8123", cfg["known_containers"])
        settings.normalize(cfg, settings.default_settings([]))   # still valid settings

    def test_one_published_port(self):
        cfg = scanned()
        discovery.apply(cfg, [c("thing", [("0.0.0.0", 7000)])])
        self.assertEqual((row(cfg, "thing")["port"], row(cfg, "thing")["port_options"]), (7000, []))

    def test_loopback_port_ignored_ipv4_ipv6_once(self):
        self.assertEqual(discovery.published_ports(c("a", [("127.0.0.1", 2375)])), [])
        self.assertEqual(discovery.published_ports(c("a", [("::1", 2375)])), [])
        self.assertEqual(discovery.published_ports(c("a", [("0.0.0.0", 7892), ("::", 7892)])), [7892])

    def test_several_ports_ask(self):
        cfg = scanned()
        discovery.apply(cfg, [c("thing", [("0.0.0.0", 8080), ("0.0.0.0", 3000)])])
        self.assertEqual((row(cfg, "thing")["port"], row(cfg, "thing")["port_options"]), (None, [3000, 8080]))

    def test_port_from_name_when_none_published(self):
        cfg = scanned()
        discovery.apply(cfg, [c("thing-9000")])
        self.assertEqual(row(cfg, "thing-9000")["port"], 9000)
        self.assertEqual(row(cfg, "thing-9000")["name"], "Thing")

    def test_name_port_rejects_junk(self):
        self.assertEqual(discovery.name_port("thing-9000"), 9000)
        for name in ("thing", "thing-70000", "app-1", "thing-0080x", "thing-123456", "thing-00"):
            self.assertIsNone(discovery.name_port(name), name)

    def test_no_port_at_all_asks(self):
        cfg = scanned()
        discovery.apply(cfg, [c("thing")])
        self.assertEqual((row(cfg, "thing")["port"], row(cfg, "thing")["port_options"]), (None, []))

    def test_gone_or_stopped_marked_not_running(self):
        cfg = scanned("thing-9000")
        discovery.apply(cfg, [c("thing-9000"), c("late-9001")])
        self.assertTrue(discovery.apply(cfg, [c("thing-9000")]))
        self.assertFalse(row(cfg, "late-9001")["running"])
        self.assertTrue(discovery.apply(cfg, [c("thing-9000"), c("late-9001")]))
        self.assertTrue(row(cfg, "late-9001")["running"])
        self.assertTrue(discovery.apply(cfg, [c("thing-9000"), c("late-9001", state="exited")]))
        self.assertFalse(row(cfg, "late-9001")["running"])

    def test_seeded_service_tracks_its_container(self):
        cfg = scanned("home-3001")
        self.assertTrue(row(cfg, "home-3001")["running"])
        self.assertFalse(row(cfg, "firefox-app-1")["running"])

    def test_known_container_never_reappears_as_new(self):
        cfg = scanned("exporter-9100")
        before = len(cfg["services"])
        discovery.apply(cfg, [])
        discovery.apply(cfg, [c("exporter-9100")])
        self.assertEqual(len(cfg["services"]), before)

    def test_ignored_stays_ignored(self):
        cfg = scanned()
        discovery.apply(cfg, [c("helper-1234")])
        row(cfg, "helper-1234")["state"] = "ignored"
        discovery.apply(cfg, [c("helper-1234")])
        self.assertEqual(row(cfg, "helper-1234")["state"], "ignored")
        self.assertEqual(len([s for s in cfg["services"] if s["container"] == "helper-1234"]), 1)

    def test_removed_row_comes_back_as_new_if_it_returns(self):
        cfg = scanned()
        discovery.apply(cfg, [c("thing-9000")])
        discovery.remove(cfg, "c-thing-9000")
        self.assertFalse(any(s["container"] == "thing-9000" for s in cfg["services"]))
        discovery.apply(cfg, [c("thing-9000")])
        self.assertEqual(row(cfg, "thing-9000")["state"], "new")

    def test_long_name_stays_valid(self):
        cfg = scanned()
        discovery.apply(cfg, [c("x" * 90)])
        settings.normalize(cfg, settings.default_settings([]))

    def test_unnamed_container_skipped(self):
        cfg = scanned()
        self.assertFalse(discovery.apply(cfg, [{"Names": [], "State": "running"}]))
