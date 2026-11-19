"""Which stretch of time is one "camera day".

A day's video covers one stretch of daylight, not midnight to midnight. At a
northern camera in June the light lasts past midnight, and a video cut at
midnight (or made at a fixed evening hour) loses the end of the day: at 56 N
on Alaska time the June sun sets just after midnight and it is light enough
to see until after 1 AM.

So the window for day D starts at the dawn that falls on D and ends at the
first dusk after it, even when that dusk is on the next calendar date. The
video is named for D, the date the light began.

Nothing here reads a clock or a file: every function takes its date.
"""

from datetime import datetime, time, timedelta, timezone

from astral import Observer
from astral.sun import dawn, dusk, sunrise, sunset

import settings

CIVIL_DEPRESSION = 6


def _solar_zone(observer):
    """A fixed zone whose noon is roughly when the sun is highest here."""
    return timezone(timedelta(hours=round(observer.longitude / 15)))


def _events(fn, day, observer, tz, **kwargs):
    """Every time `fn` (a dawn, dusk, sunrise or sunset) happens near `day`,
    as times in `tz`.

    The sun library answers "the sunset on this date", and that question has
    no good answer in a zone where sunset drifts across midnight: far west in
    a time zone there is a July date with two sunsets (00:01 and 23:59) and
    the date before it has none, so one of them is never returned. Asked in
    the place's own solar time the events sit in the morning and the evening,
    well away from midnight, and each date has exactly one. So: ask in solar
    time, for the neighbouring dates too, and convert.
    """
    solar = _solar_zone(observer)
    found = set()
    for offset in range(-2, 3):
        try:
            found.add(fn(observer, date=day + timedelta(days=offset), tzinfo=solar,
                         **kwargs).astimezone(tz).replace(microsecond=0))
        except ValueError:
            pass        # the sun does not reach that point on that date
    return sorted(found)


def _light(day, mode, observer, tz):
    """(start, end) of the light on `day` with no margin, or None when the
    sun does not make both events (midnight sun, polar night)."""
    if mode == 'civil':
        starts = _events(dawn, day, observer, tz, depression=CIVIL_DEPRESSION)
        ends = _events(dusk, day, observer, tz, depression=CIVIL_DEPRESSION)
    else:
        starts = _events(sunrise, day, observer, tz)
        ends = _events(sunset, day, observer, tz)
    starts = [t for t in starts if t.date() == day]
    if not starts:
        return None
    start = starts[0]
    ends = [t for t in ends if t > start]
    if not ends or ends[0] - start >= timedelta(hours=24):
        return None
    return start, ends[0]


def window(day, mode=None, margin_min=None, lat=None, lon=None, tz=None):
    """The daylight window for camera day `day` (a date): two aware datetimes.

    Falls back from civil twilight to sunrise/sunset plus an hour, and from
    that to the whole calendar day, when the sun does not cooperate. A window
    never runs into the next day's.
    """
    mode = (mode or settings.DAYLIGHT_MODE).lower()
    margin = timedelta(minutes=settings.DAYLIGHT_MARGIN_MIN if margin_min is None else margin_min)
    tz = tz or settings.TZ
    observer = Observer(latitude=settings.CAMERA_LAT if lat is None else lat,
                        longitude=settings.CAMERA_LON if lon is None else lon)

    def bounds(d):
        light = _light(d, mode, observer, tz)
        if light:
            return light[0] - margin, light[1] + margin
        if mode == 'civil':
            light = _light(d, 'sun', observer, tz)
            if light:
                return light[0] - timedelta(hours=1), light[1] + timedelta(hours=1)
        midnight = datetime.combine(d, time(0), tzinfo=tz)
        return midnight, datetime.combine(d + timedelta(days=1), time(0), tzinfo=tz)

    start, end = bounds(day)
    next_start = bounds(day + timedelta(days=1))[0]
    if end > next_start:
        end = next_start
    return start, end


def closed_days(now, back):
    """Camera days, oldest first, whose window has closed (with the render
    grace) by `now`, looking `back` days into the past."""
    grace = timedelta(minutes=settings.RENDER_GRACE_MIN)
    today = now.astimezone(settings.TZ).date()
    days = []
    for offset in range(back, -1, -1):
        day = today - timedelta(days=offset)
        if window(day)[1] + grace <= now:
            days.append(day)
    return days
