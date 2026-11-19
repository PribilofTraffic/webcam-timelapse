"""The record of which days have a video.

The source of truth is a small SQLite database in the data folder. The JSON
index the web pages read (timelapse_metadata.json) is written FROM it after
every change, whole and atomically, so losing or tearing that file costs
nothing: the next video rewrites it.

Tables:
  videos    one row per camera day that has a video
  attempts  days a video could not be made for, so they are retried a few
            times and then left alone, not hammered every five minutes
"""

import json
import os
import sqlite3
from datetime import date, datetime

import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    day              TEXT PRIMARY KEY,   -- YYYY-MM-DD, the date the light began
    filename         TEXT NOT NULL,
    image_count      INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    size_mb          REAL NOT NULL,
    generated_at     TEXT NOT NULL,
    window_start     TEXT,               -- first and last moment the video covers
    window_end       TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    day       TEXT PRIMARY KEY,
    tries     INTEGER NOT NULL,
    last_try  TEXT NOT NULL,
    result    TEXT NOT NULL
);
"""


def connect(path=None):
    path = path or settings.DB_PATH
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def has_video(conn, day):
    return conn.execute('SELECT 1 FROM videos WHERE day = ?', (str(day),)).fetchone() is not None


def video_days(conn):
    return {date.fromisoformat(row['day']) for row in conn.execute('SELECT day FROM videos')}


def add_video(conn, day, filename, image_count, duration_seconds, size_mb,
              generated_at, window_start=None, window_end=None):
    with conn:
        conn.execute(
            'INSERT OR REPLACE INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (str(day), filename, int(image_count), float(duration_seconds),
             float(size_mb), generated_at, window_start, window_end))
        conn.execute('DELETE FROM attempts WHERE day = ?', (str(day),))


def note_attempt(conn, day, result, when):
    with conn:
        conn.execute(
            'INSERT INTO attempts (day, tries, last_try, result) VALUES (?, 1, ?, ?) '
            'ON CONFLICT(day) DO UPDATE SET tries = tries + 1, last_try = excluded.last_try, '
            'result = excluded.result', (str(day), when, result))


def attempt(conn, day):
    row = conn.execute('SELECT tries, last_try, result FROM attempts WHERE day = ?',
                       (str(day),)).fetchone()
    return dict(row) if row else None


def latest(conn):
    row = conn.execute('SELECT * FROM videos ORDER BY day DESC LIMIT 1').fetchone()
    return dict(row) if row else None


def index_payload(conn, now):
    """What the web pages read. Same keys the cron script wrote, so no page
    changes: type, date, filename, path, image_count, duration_seconds,
    size_mb, generated_at. `path` is the public path, never a folder on the
    server."""
    rows = conn.execute('SELECT * FROM videos ORDER BY day').fetchall()
    return {
        'timelapses': [{
            'type': 'daily',
            'date': row['day'],
            'filename': row['filename'],
            'path': settings.PUBLIC_VIDEO_PATH + row['filename'],
            'image_count': row['image_count'],
            'duration_seconds': row['duration_seconds'],
            'size_mb': row['size_mb'],
            'generated_at': row['generated_at'],
        } for row in rows],
        'last_updated': f'{now:%Y-%m-%d %H:%M:%S %Z}',
    }


def write_index(conn, now=None, path=None):
    path = path or settings.INDEX_FILE
    now = now or datetime.now(settings.TZ)
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(index_payload(conn, now), fh, indent=2)
    os.replace(tmp, path)


def import_legacy(conn, path=None, video_dir=None):
    """Take the videos an earlier setup made, from the index it wrote.

    Runs until it has succeeded once (remembered in the database), and adds
    only days that have no row yet, so it does not matter whether a video was
    recorded here first. Only daily videos whose file is really in the video
    folder are taken: an entry for a video that no longer exists (old weekly
    and monthly ones) would be a dead link on the page. Returns how many were
    taken; a missing or unreadable file takes none and is tried again later.
    """
    path = path or settings.LEGACY_INDEX
    video_dir = video_dir or settings.VIDEO_DIR
    if conn.execute("SELECT 1 FROM meta WHERE key = 'legacy_imported'").fetchone():
        return 0
    try:
        with open(path) as fh:
            entries = json.load(fh).get('timelapses') or []
    except (OSError, ValueError, AttributeError):
        return 0
    taken = 0
    for entry in entries:
        try:
            if entry.get('type') != 'daily':
                continue
            day = date.fromisoformat(entry['date'])
            filename = os.path.basename(entry['filename'])
            if has_video(conn, day) or not os.path.isfile(os.path.join(video_dir, filename)):
                continue
            add_video(conn, day, filename, entry.get('image_count') or 0,
                      entry.get('duration_seconds') or 0.0, entry.get('size_mb') or 0.0,
                      (entry.get('generated_at') or '').strip())
            taken += 1
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('legacy_imported', ?)",
                     (datetime.now(settings.TZ).isoformat(timespec='seconds'),))
    return taken
