"""Optional weather lookup. Off by default; the app is fully functional without it.

When the user opts in we send only coordinates rounded to ~11 km (one decimal place) to
Open-Meteo, which needs no API key. Any failure is swallowed: weather is a nicety.
"""

from __future__ import annotations

from datetime import date

import httpx

_WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
        51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
        65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
        81: "rain showers", 82: "heavy showers", 95: "thunderstorms", 96: "thunderstorms with hail",
        99: "thunderstorms with hail"}


def fetch_weather(lat: float, lon: float, on: date, transport: httpx.BaseTransport | None = None) -> dict | None:
    params = {
        "latitude": round(lat, 1), "longitude": round(lon, 1), "timezone": "auto",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "start_date": on.isoformat(), "end_date": on.isoformat(),
    }
    try:
        with httpx.Client(timeout=6.0, transport=transport) as c:
            r = c.get("https://api.open-meteo.com/v1/forecast", params=params)
            r.raise_for_status()
            d = r.json()["daily"]
        return {
            "summary": _WMO.get(int(d["weather_code"][0]), "mixed conditions"),
            "high_c": d["temperature_2m_max"][0],
            "low_c": d["temperature_2m_min"][0],
            "rain_chance_pct": d["precipitation_probability_max"][0],
        }
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return None
