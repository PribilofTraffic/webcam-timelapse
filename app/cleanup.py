#!/usr/bin/env python3
"""Delete frames older than the retention period, once their video exists.

The video is the thing that is kept; the frames are raw material. So a day's
frames go only when:

  - the day is older than WEBCAM_RETENTION_DAYS (default 30), and
  - that day's video is on record AND its file is really there, and
  - the day before is settled too (has its video, or has no frames left).
    A summer video runs past midnight into the next date's folder, so the
    first hours of a folder can belong to the day before.

A day with no video is kept and named in the output, never deleted: without
the video those frames are the only copy of the day.

Only folders shaped YYYY/MM/DD under the frames folder are ever touched.
Anything else in there (a web page, a stray file) is left alone. Videos are
never touched.

WEBCAM_CLEANUP_DRY_RUN=1 (or --dry-run) reports and deletes nothing.
"""

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta

import frames
import index_db
import settings

settings.apply_timezone()


def numbered(folder, digits):
    """Sub-folders whose name is exactly `digits` digits, in order. Links are
    not followed."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [n for n in names if len(n) == digits and n.isdigit()
            and os.path.isdir(os.path.join(folder, n))
            and not os.path.islink(os.path.join(folder, n))]


def archived_days(root):
    """Every (date, folder) in the archive, oldest first."""
    days = []
    for year in numbered(root, 4):
        for month in numbered(os.path.join(root, year), 2):
            for day in numbered(os.path.join(root, year, month), 2):
                try:
                    days.append((date(int(year), int(month), int(day)),
                                 os.path.join(root, year, month, day)))
                except ValueError:
                    continue
    return days


def folder_bytes(folder):
    total = 0
    for base, _, names in os.walk(folder):
        for name in names:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def clean(root, today, has_video, retain_days=None, dry_run=False):
    """Returns a summary dict. `has_video(day)` says whether the day's video
    is safely made."""
    retain_days = settings.RETENTION_DAYS if retain_days is None else max(2, retain_days)
    cutoff = today - timedelta(days=retain_days)
    days = archived_days(root)
    still_there = {day for day, _ in days}
    removed, waiting, freed, kept, kept_bytes = [], [], 0, 0, 0
    for day, folder in days:
        size = folder_bytes(folder)
        if day >= cutoff:
            kept += 1
            kept_bytes += size
            continue
        before = day - timedelta(days=1)
        settled = has_video(day) and (has_video(before) or before not in still_there)
        if not settled:
            waiting.append(str(day))
            kept_bytes += size
            continue
        if not dry_run:
            shutil.rmtree(folder)
            still_there.discard(day)
        removed.append(str(day))
        freed += size
    if not dry_run:
        # Month and year folders left empty by the above; nothing else.
        for year in numbered(root, 4):
            for month in numbered(os.path.join(root, year), 2):
                path = os.path.join(root, year, month)
                if not os.listdir(path):
                    os.rmdir(path)
            path = os.path.join(root, year)
            if not os.listdir(path):
                os.rmdir(path)
    return {'dry_run': dry_run, 'retain_days': retain_days, 'removed': removed,
            'waiting_for_video': waiting, 'freed_gb': round(freed / 1024 ** 3, 2),
            'days_kept': kept + len(waiting), 'kept_gb': round(kept_bytes / 1024 ** 3, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    dry_run = args.dry_run or settings.CLEANUP_DRY_RUN

    conn = index_db.connect()
    try:
        on_record = index_db.video_days(conn)
    finally:
        conn.close()

    def has_video(day):
        return day in on_record and os.path.isfile(settings.video_file(day))

    summary = clean(settings.FRAMES_DIR, datetime.now(settings.TZ).date(), has_video, dry_run=dry_run)
    verb = 'would remove' if dry_run else 'removed'
    print(f"clean-up{' (dry run)' if dry_run else ''}: {verb} {len(summary['removed'])} day(s), "
          f"{summary['freed_gb']} GB; {summary['days_kept']} day(s) kept, {summary['kept_gb']} GB")
    if summary['removed']:
        print(f"  {verb}: {', '.join(summary['removed'])}")
    if summary['waiting_for_video']:
        print(f"  kept because there is no video yet: {', '.join(summary['waiting_for_video'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
