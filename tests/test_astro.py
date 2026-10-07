from datetime import date, timedelta

from trailcard.astro import daylight_note, season, sun_times


def _local(dt, hours):
    return dt + timedelta(hours=hours)


def test_seattle_sun_times_match_open_meteo_within_five_minutes():
    # Open-Meteo reference for 2026-10-07: sunrise 07:16, sunset 18:36 (UTC-7)
    rise, sset = sun_times(47.6062, -122.3321, date(2026, 10, 7))
    r, s = _local(rise, -7), _local(sset, -7)
    assert abs((r.hour * 60 + r.minute) - (7 * 60 + 16)) <= 5
    assert abs((s.hour * 60 + s.minute) - (18 * 60 + 36)) <= 5


def test_sydney_sun_times_match_open_meteo_within_five_minutes():
    # Open-Meteo reference for 2026-10-07: sunrise 06:24, sunset 19:02 (UTC+11)
    rise, sset = sun_times(-33.87, 151.21, date(2026, 10, 7))
    r, s = _local(rise, 11), _local(sset, 11)
    assert abs((r.hour * 60 + r.minute) - (6 * 60 + 24)) <= 5
    assert abs((s.hour * 60 + s.minute) - (19 * 60 + 2)) <= 5


def test_polar_summer_has_no_sunset():
    assert sun_times(78.2, 15.6, date(2026, 6, 21)) == (None, None)
    assert "No sunset" in daylight_note(None, 0)


def test_season_flips_in_southern_hemisphere():
    assert season(47.6, date(2026, 10, 7)) == "autumn"
    assert season(-33.9, date(2026, 10, 7)) == "spring"
    assert season(40.0, date(2026, 1, 15)) == "winter"
    assert season(-40.0, date(2026, 1, 15)) == "summer"
