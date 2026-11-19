"""Where frames live on disk and how to find the ones for a stretch of time.

Layout (unchanged from the cron script this replaces, so an existing archive
is picked up as it is):

    <frames>/YYYY/MM/DD/HH/image_YYYYMMDD_HHMMSS.jpg

The date and time in the name are the camera's local time.
"""

import os
import re
from datetime import datetime, timedelta

import settings

NAME = re.compile(r'^image_(\d{8})_(\d{6})\.jpg$')


def frame_path(root, when):
    """The file a frame taken at `when` (local time) is saved as."""
    return os.path.join(root, f'{when:%Y}', f'{when:%m}', f'{when:%d}', f'{when:%H}',
                        f'image_{when:%Y%m%d_%H%M%S}.jpg')


def frame_time(path, tz=None):
    """The local time a frame was taken, read from its name; None if the name
    is not a frame's."""
    match = NAME.match(os.path.basename(path))
    if not match:
        return None
    try:
        naive = datetime.strptime(match.group(1) + match.group(2), '%Y%m%d%H%M%S')
    except ValueError:
        return None
    return naive.replace(tzinfo=tz or settings.TZ)


def day_dir(root, day):
    return os.path.join(root, f'{day:%Y}', f'{day:%m}', f'{day:%d}')


def frames_between(root, start, end, tz=None):
    """Every frame taken from `start` to `end` (aware datetimes), in order.

    Walks only the hour folders the stretch touches, so a window that runs
    past midnight reads the first hours of the next date's folder and
    nothing else.
    """
    tz = tz or settings.TZ
    start, end = start.astimezone(tz), end.astimezone(tz)
    found = []
    hour = start.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    last = end.replace(tzinfo=None)
    while hour <= last:
        folder = os.path.join(day_dir(root, hour), f'{hour:%H}')
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            taken = frame_time(name, tz)
            if taken is not None and start <= taken <= end:
                found.append((taken, os.path.join(folder, name)))
        hour += timedelta(hours=1)
    found.sort()
    return [path for _, path in found]


def count_day(root, day):
    """How many frames are filed under one calendar date."""
    total = 0
    for _, _, names in os.walk(day_dir(root, day)):
        total += sum(1 for name in names if NAME.match(name))
    return total
