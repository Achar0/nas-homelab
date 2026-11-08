import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weather  # noqa: E402

MORNING = datetime(2026, 11, 7, 7, 42)
NOTHING = "Nice day, nothing special to bring"


def raw(rain_at=None, code_at=None, temp_at=None, sun_at=None, wind_at=None, current_code=3):
    """72 mild, dry, cloudy hours from 2026-11-07 00:00; *_at override single hours by index."""
    start = datetime(2026, 11, 7)
    def series(default, over):
        return [(over or {}).get(i, default) for i in range(72)]
    return {"current": {"temperature_2m": 12.4, "apparent_temperature": 10.6, "weather_code": current_code},
            "hourly": {"time": [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(72)],
                       "temperature_2m": series(14, temp_at), "precipitation_probability": series(10, rain_at),
                       "weather_code": series(3, code_at), "wind_speed_10m": series(5, wind_at),
                       "uv_index": series(1, sun_at)}}


def tip(now=MORNING, **over):
    return weather.build(raw(**over), now, 0)["tip"]


class Tip(unittest.TestCase):
    def test_nothing_special(self):
        self.assertEqual(tip()["zh"], "天气不错，无需特别准备")
        self.assertEqual(tip()["en"], NOTHING)

    def test_rain_at_the_threshold(self):
        self.assertEqual(tip(rain_at={9: 50})["en"], "Bring an umbrella")
        self.assertEqual(tip(rain_at={9: 49})["en"], NOTHING)

    def test_cold_below_eight_only(self):
        self.assertEqual(tip(temp_at={10: 7.9})["en"], "Wear a warm jacket")
        self.assertEqual(tip(temp_at={10: 8})["en"], NOTHING)

    def test_windy_means_jacket(self):
        self.assertEqual(tip(wind_at={10: 30})["en"], "Wear a warm jacket")

    def test_sun_needs_clear_sky_and_high_uv(self):
        clear = {i: 1 for i in range(72)}
        self.assertEqual(tip(code_at=clear, sun_at={12: 6})["en"], "Sunglasses and sunscreen")
        self.assertEqual(tip(code_at=clear, sun_at={12: 5})["en"], NOTHING)
        self.assertEqual(tip(sun_at={12: 7})["en"], NOTHING)  # cloudy hour

    def test_freezing_code_is_ice(self):
        self.assertEqual(tip(code_at={9: 66})["en"], "Leave early, drive carefully")

    def test_near_freezing_rain_is_ice(self):
        t = tip(temp_at={9: 1}, rain_at={9: 60})
        self.assertTrue(t["en"].startswith("Leave early, drive carefully"))

    def test_fog_beats_rain_and_two_items_at_most(self):
        t = tip(code_at={9: 45}, rain_at={10: 80}, temp_at={11: 3}, sun_at={12: 7})
        self.assertEqual(t["en"], "Leave early, drive carefully · Bring an umbrella")
        self.assertEqual(t["zh"], "路上小心，早点出门，记得带伞")

    def test_morning_ignores_hours_beyond_the_window(self):
        self.assertEqual(tip(rain_at={16: 90})["en"], NOTHING)

    def test_past_hours_do_not_count(self):
        self.assertEqual(tip(rain_at={5: 90})["en"], NOTHING)

    def test_from_18_looks_at_tomorrow_until_noon(self):
        at18 = datetime(2026, 11, 7, 18, 0)
        self.assertEqual(tip(now=at18, rain_at={11 + 24: 90})["en"], "Bring an umbrella")
        self.assertEqual(tip(now=at18, rain_at={13 + 24: 90})["en"], NOTHING)

    def test_just_before_18_uses_the_short_window(self):
        self.assertEqual(tip(now=datetime(2026, 11, 7, 17, 59), rain_at={11 + 24: 90})["en"], NOTHING)


class Build(unittest.TestCase):
    def test_hours_are_four_three_hour_points(self):
        w = weather.build(raw(), MORNING, 0)
        self.assertEqual([h["label"] for h in w["hours"]], ["09", "12", "15", "18"])

    def test_hours_wrap_past_midnight(self):
        w = weather.build(raw(), datetime(2026, 11, 7, 22, 10), 0)
        self.assertEqual([h["label"] for h in w["hours"]], ["00", "03", "06", "09"])

    def test_now_is_rounded_and_described(self):
        now = weather.build(raw(current_code=61), MORNING, 0)["now"]
        self.assertEqual((now["temp"], now["feels"]), (12, 11))
        self.assertEqual((now["zh"], now["en"]), ("小雨", "Light rain"))

    def test_unknown_code_still_renders(self):
        self.assertTrue(weather.build(raw(current_code=999), MORNING, 0)["now"]["zh"])

    def test_fetched_is_kept(self):
        self.assertEqual(weather.build(raw(), MORNING, 123.0)["fetched"], 123.0)


class Fresh(unittest.TestCase):
    def test_stale_weather_is_dropped(self):
        self.assertIsNone(weather.fresh({"fetched": 0}, 3 * 3600 + 1))
        self.assertIsNotNone(weather.fresh({"fetched": 0}, 3 * 3600))
        self.assertIsNone(weather.fresh(None, 0))
