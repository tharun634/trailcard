"""Offline sun and season maths, so a card works with no network at all.

Sunrise/sunset use the NOAA solar-position approximation (accurate to about a minute at
mid latitudes), which is plenty for "be back before dark".
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

_NORTH = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
          6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
_FLIP = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}


def season(lat: float, on: date) -> str:
    """Meteorological season, flipped for the southern hemisphere."""
    s = _NORTH[on.month]
    return s if lat >= 0 else _FLIP[s]


def sun_times(lat: float, lon: float, on: date) -> tuple[datetime | None, datetime | None]:
    """Return (sunrise, sunset) as aware UTC datetimes, or (None, None) in polar day/night."""
    n = on.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat_r = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
              - math.tan(lat_r) * math.tan(decl))
    if cos_ha > 1 or cos_ha < -1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
    rise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    sset = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    return rise, sset


def daylight_note(sunset: datetime | None, utc_offset_min: int) -> str:
    """Human-readable local sunset line; ``utc_offset_min`` is the user's UTC offset in minutes."""
    if sunset is None:
        return "No sunset today (polar day or night), so plan around the clock instead."
    local = sunset + timedelta(minutes=utc_offset_min)
    return f"Sunset about {local:%H:%M} local time. Be back at least 30 minutes before."
