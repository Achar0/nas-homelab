"""Milan weather and the what-to-bring tip for the TV page (pure, no I/O).

All Chinese and English text is fixed here: nothing is machine-translated.
"""
from datetime import datetime, timedelta

URL = ("https://api.open-meteo.com/v1/forecast?latitude=45.4642&longitude=9.19"
       "&current=temperature_2m,apparent_temperature,weather_code"
       "&hourly=temperature_2m,precipitation_probability,weather_code,wind_speed_10m,uv_index"
       "&timezone=Europe/Rome&forecast_days=3")

RAIN_PROB = 50       # %
COLD_C = 8
ICE_C = 1
WIND_KMH = 30
UV_HIGH = 6
MAX_AGE = 3 * 3600   # seconds: older weather is hidden rather than shown as current
WINDOW_H = 8
EVENING_FROM = 18    # from this hour the tip covers tonight and tomorrow morning
TOMORROW_UNTIL = 12

FOG_CODES = {45, 48}
FREEZING_CODES = {56, 57, 66, 67}
SUNNY_CODES = {0, 1}

# WMO weather code -> (icon, Chinese, English)
CODES = {
    0: ("☀️", "晴", "Clear"), 1: ("🌤", "晴间多云", "Mostly clear"), 2: ("⛅", "多云", "Partly cloudy"),
    3: ("☁️", "阴", "Overcast"), 45: ("🌫", "雾", "Fog"), 48: ("🌫", "雾凇", "Freezing fog"),
    51: ("🌦", "毛毛雨", "Light drizzle"), 53: ("🌦", "毛毛雨", "Drizzle"), 55: ("🌧", "毛毛雨", "Heavy drizzle"),
    56: ("🌧", "冻毛毛雨", "Freezing drizzle"), 57: ("🌧", "冻毛毛雨", "Freezing drizzle"),
    61: ("🌦", "小雨", "Light rain"), 63: ("🌧", "中雨", "Rain"), 65: ("🌧", "大雨", "Heavy rain"),
    66: ("🌧", "冻雨", "Freezing rain"), 67: ("🌧", "冻雨", "Freezing rain"),
    71: ("🌨", "小雪", "Light snow"), 73: ("🌨", "中雪", "Snow"), 75: ("❄️", "大雪", "Heavy snow"), 77: ("🌨", "雪粒", "Snow grains"),
    80: ("🌦", "阵雨", "Showers"), 81: ("🌧", "阵雨", "Showers"), 82: ("🌧", "强阵雨", "Heavy showers"),
    85: ("🌨", "阵雪", "Snow showers"), 86: ("❄️", "强阵雪", "Heavy snow showers"),
    95: ("⛈", "雷雨", "Thunderstorm"), 96: ("⛈", "雷雨伴冰雹", "Thunderstorm, hail"), 99: ("⛈", "雷雨伴冰雹", "Thunderstorm, hail"),
}
UNKNOWN_CODE = ("🌡", "天气", "Weather")

ICE = ("🚗", "路上小心，早点出门", "Leave early, drive carefully")
RAIN = ("☂️", "记得带伞", "Bring an umbrella")
COLD = ("🧥", "穿暖和点", "Wear a warm jacket")
SUN = ("🕶", "戴墨镜，涂防晒", "Sunglasses and sunscreen")
NOTHING = {"icon": "✨", "zh": "天气不错，无需特别准备", "en": "Nice day, nothing special to bring"}


def _hours(raw):
    h = raw["hourly"]
    return [{"t": datetime.fromisoformat(t), "temp": temp, "rain": rain or 0, "code": code, "wind": wind or 0, "uv": uv or 0}
            for t, temp, rain, code, wind, uv in zip(h["time"], h["temperature_2m"], h["precipitation_probability"],
                                                      h["weather_code"], h["wind_speed_10m"], h["uv_index"])
            if temp is not None]


def _window(hours, now):
    start = now.replace(minute=0, second=0, microsecond=0)
    if now.hour >= EVENING_FROM:
        tomorrow = start.replace(hour=TOMORROW_UNTIL) + timedelta(days=1)
        return [h for h in hours if start <= h["t"] <= tomorrow]
    return [h for h in hours if start <= h["t"] < start + timedelta(hours=WINDOW_H)]


def _tip(hours):
    wet = lambda h: h["rain"] >= RAIN_PROB  # noqa: E731
    rules = ((ICE, lambda h: h["code"] in FOG_CODES | FREEZING_CODES or (h["temp"] <= ICE_C and wet(h))),
             (RAIN, wet),
             (COLD, lambda h: h["temp"] < COLD_C or h["wind"] >= WIND_KMH),
             (SUN, lambda h: h["code"] in SUNNY_CODES and h["uv"] >= UV_HIGH))
    items = [text for text, hit in rules if any(hit(h) for h in hours)][:2]
    if not items:
        return NOTHING
    return {"icon": items[0][0], "zh": "，".join(i[1] for i in items), "en": " · ".join(i[2] for i in items)}


def build(raw, now, fetched):
    """Open-Meteo's answer -> what the TV page shows. `now` is naive local time (Europe/Rome)."""
    hours = _hours(raw)
    cur = raw["current"]
    icon, zh, en = CODES.get(cur["weather_code"], UNKNOWN_CODE)
    points = [h for h in hours if h["t"] > now and h["t"].hour % 3 == 0][:4]
    return {"now": {"temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]), "icon": icon, "zh": zh, "en": en},
            "hours": [{"label": f"{h['t'].hour:02d}", "temp": round(h["temp"]), "icon": CODES.get(h["code"], UNKNOWN_CODE)[0]} for h in points],
            "tip": _tip(_window(hours, now)), "fetched": fetched}


def fresh(w, now):
    """The weather if it is recent enough to show, else None."""
    return w if w and now - w["fetched"] <= MAX_AGE else None
