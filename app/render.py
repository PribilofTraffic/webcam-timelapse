#!/usr/bin/env python3
"""Make the video for every camera day that is finished and has none.

Run every few minutes by run.py; it exits at once when nothing is due. A day
is due when its daylight window (see daylight.py) closed more than the grace
period ago. That is a different clock time every day: early evening in
December, after 1 AM in June at 56 N.

By hand:
    python render.py                       what the scheduler runs
    python render.py --day 2026-06-20      make (or remake) one day's video
    python render.py --day 2026-06-20 --dry-run     say what it would cover
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

import daylight
import frames
import index_db
import settings
import share_page
import video

settings.apply_timezone()

RETRY_AFTER = timedelta(hours=1)


def due_days(conn, now):
    """Finished camera days with no video that are worth trying now."""
    due = []
    for day in daylight.closed_days(now, settings.CATCH_UP_DAYS):
        if index_db.has_video(conn, day):
            continue
        tried = index_db.attempt(conn, day)
        if tried:
            if tried['tries'] >= settings.MAX_RENDER_TRIES:
                continue
            if now - datetime.fromisoformat(tried['last_try']) < RETRY_AFTER:
                continue
        due.append(day)
    return due


def make(conn, day, now, force=False):
    """Make one day's video and record it. Returns (ok, message)."""
    start, end = daylight.window(day)
    pictures = frames.frames_between(settings.RENDER_FROM_DIR, start, end)
    span = f'{start:%H:%M} to {end:%H:%M %Z}' + (' next day' if end.date() != day else '')
    if len(pictures) < settings.MIN_FRAMES:
        message = f'{day}: only {len(pictures)} frames between {span}; no video'
        if not force:
            index_db.note_attempt(conn, day, f'{len(pictures)} frames', now.isoformat(timespec='seconds'))
        return False, message
    output = settings.video_file(day)
    ok, why = video.render(pictures, output, f'{settings.CAMERA_NAME} - {day:%B %d, %Y}')
    if not ok:
        index_db.note_attempt(conn, day, why[:200], now.isoformat(timespec='seconds'))
        return False, f'{day}: {why}'
    size_mb = round(os.path.getsize(output) / 1024 ** 2, 2)
    index_db.add_video(
        conn, day, os.path.basename(output), len(pictures),
        round(len(pictures) / settings.FRAMERATE, 2), size_mb,
        f'{datetime.now(settings.TZ):%Y-%m-%d %H:%M:%S %Z}',
        start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds'))
    try:
        share_page.write(day, len(pictures))
    except OSError as exc:
        print(f'{day}: video made, share page not written ({type(exc).__name__})')
    index_db.write_index(conn)
    return True, f'{day}: {len(pictures)} frames, {span}, {size_mb} MB -> {os.path.basename(output)}'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--day', help='make this camera day (YYYY-MM-DD), even if it has a video')
    parser.add_argument('--dry-run', action='store_true', help='say what would be made; make nothing')
    args = parser.parse_args()

    now = datetime.now(settings.TZ)
    conn = index_db.connect()
    try:
        seeded = index_db.import_legacy(conn)
        if seeded:
            print(f'took {seeded} existing videos from the earlier index')
            index_db.write_index(conn)
        if not os.path.isfile(settings.INDEX_FILE):
            index_db.write_index(conn)

        days = [date.fromisoformat(args.day)] if args.day else due_days(conn, now)
        failed = 0
        for day in days:
            if args.dry_run:
                start, end = daylight.window(day)
                count = len(frames.frames_between(settings.RENDER_FROM_DIR, start, end))
                print(f'{day}: would cover {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M %Z}, {count} frames')
                continue
            ok, message = make(conn, day, now, force=bool(args.day))
            print(message)
            failed += 0 if ok else 1
        return 1 if failed else 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
