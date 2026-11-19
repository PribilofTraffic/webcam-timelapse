#!/usr/bin/env python3
"""Dated copies of the video index database.

The database is small, but it is the only record of which days have a video
and what each one covers. Once a day this writes a copy into WEBCAM_BACKUP_DIR/<YYYY-MM-DD>/ and
removes the oldest folders beyond WEBCAM_BACKUP_KEEP (default 3).

The copy is made with SQLite's own backup call, which is consistent while a
video is being recorded, and is verified before it replaces the day's copy. Off
unless WEBCAM_BACKUP_DIR is set.
"""

import glob
import os
import shutil
import sqlite3
import sys
from datetime import datetime

import settings

settings.apply_timezone()

BACKUP_DIR = settings.BACKUP_DIR
KEEP = settings.get_int('WEBCAM_BACKUP_KEEP', 3)


def backup_database(src, dst):
    """Copy src to dst and return SQLite's own verdict on the copy."""
    source = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
            return target.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            target.close()
    finally:
        source.close()


def main():
    if not BACKUP_DIR:
        print('no backup folder set (WEBCAM_BACKUP_DIR); backups are off')
        return 0
    if not os.path.isfile(settings.DB_PATH):
        print('no database yet; nothing to copy')
        return 0
    day = datetime.now(settings.TZ).strftime('%Y-%m-%d')
    folder = os.path.join(BACKUP_DIR, day)
    os.makedirs(folder, exist_ok=True)

    name = os.path.basename(settings.DB_PATH)
    tmp = os.path.join(folder, name + '.tmp')
    if os.path.exists(tmp):
        os.remove(tmp)
    verdict = backup_database(settings.DB_PATH, tmp)
    if verdict != 'ok':
        os.remove(tmp)
        print(f'backup {day} FAILED its integrity check ({verdict}); older copies kept')
        return 1
    os.replace(tmp, os.path.join(folder, name))

    # Dated folders only; anything else in the backup folder is left alone.
    dated = sorted(d for d in glob.glob(os.path.join(BACKUP_DIR, '????-??-??'))
                   if os.path.isdir(d))
    for old in dated[:-KEEP] if KEEP > 0 else []:
        shutil.rmtree(old)
        print(f'removed old backup {os.path.basename(old)}')
    print(f'backup {day}: {name} -> {folder}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
