"""Every site-specific value the webcam container uses, in one place.

Nothing else in this package names an address, a folder, a camera or a time
zone. Two sources feed this module:

1. Environment variables (WEBCAM_*): folders, the camera's address and the
   schedule. In the container they come from the compose file. A script that
   imports these modules OUTSIDE the container has no such environment, so a
   variable that is not set is looked up in an env file: WEBCAM_ENV_FILE if
   given, otherwise a `.env` in the folder above this repository.

2. A site file (JSON): the camera's name and position, how daylight is
   judged, the video settings and the public addresses used on share pages.
   See config/site.example.json, a real working setup (one camera on an
   island in the Bering Sea), which doubles as the default in a source
   checkout so the tests run with no setup.

The camera's address never goes in the site file: it is WEBCAM_URL, and
capture is switched off while that is empty.
"""

import json
import os
import time
from zoneinfo import ZoneInfo

APP_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)


def _read_env_file():
    path = os.environ.get('WEBCAM_ENV_FILE') or os.path.join(
        os.path.dirname(REPO_DIR), '.env')
    values = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'':
                    val = val[1:-1]
                values[key.strip()] = val
    except OSError:
        pass
    return values


_ENV_FILE = _read_env_file()


def get(name, default=None):
    """A setting: the environment first, then the env file, then the default.
    An empty value counts as not set."""
    val = os.environ.get(name)
    if val is None or val == '':
        val = _ENV_FILE.get(name)
    return default if val is None or val == '' else val


def get_int(name, default):
    try:
        return int(get(name, default))
    except (TypeError, ValueError):
        return default


def get_flag(name, default=False):
    val = get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ('1', 'true', 'yes', 'on')


# ---------------------------------------------------------------- folders

DATA_DIR = get('WEBCAM_DATA_DIR', '/data')        # index database, status files
CONFIG_DIR = get('WEBCAM_CONFIG_DIR', '/config')
FRAMES_DIR = get('WEBCAM_FRAMES_DIR', '/frames')  # YYYY/MM/DD/HH/image_*.jpg
VIDEO_DIR = get('WEBCAM_VIDEO_DIR', '/videos')
SHARE_DIR = get('WEBCAM_SHARE_DIR')               # share pages; off when empty
BACKUP_DIR = get('WEBCAM_BACKUP_DIR')             # off when empty
# Where the video maker reads frames from. Normally the folder capture writes
# to. A trial run points this at another (read-only) frame folder so its
# videos can be compared with the ones a running setup makes.
RENDER_FROM_DIR = get('WEBCAM_RENDER_FROM_DIR') or FRAMES_DIR


def data_path(name):
    return os.path.join(DATA_DIR, name)


def _first_existing(*paths):
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


SITE_FILE = _first_existing(
    get('WEBCAM_SITE_FILE'),
    os.path.join(CONFIG_DIR, 'site.json'),
    os.path.join(REPO_DIR, 'config', 'site.json'),
    os.path.join(REPO_DIR, 'config', 'site.example.json'),
)
SHARE_TEMPLATE = _first_existing(
    get('WEBCAM_SHARE_TEMPLATE'),
    os.path.join(CONFIG_DIR, 'share_page.html'),
    os.path.join(REPO_DIR, 'config', 'share_page.html'),
    os.path.join(REPO_DIR, 'config', 'share_page.example.html'),
)

DB_PATH = get('WEBCAM_DB_PATH') or data_path('timelapse.db')
INDEX_FILE = data_path('timelapse_metadata.json')   # what the web pages read
STATUS_FILE = data_path('webcam_status.json')
# An index written by an earlier setup; read once, to seed an empty database.
LEGACY_INDEX = get('WEBCAM_LEGACY_INDEX') or data_path('timelapse_metadata.legacy.json')


def _load_site():
    if not SITE_FILE:
        return {}
    with open(SITE_FILE) as fh:
        return json.load(fh)


SITE = _load_site()

# ---------------------------------------------------------------- time zone
# Frames are filed under the camera's local date and hour, so set this once
# and leave it.

TZ_NAME = (get('WEBCAM_TZ') or SITE.get('timezone')
           or os.environ.get('TZ') or 'UTC')
TZ = ZoneInfo(TZ_NAME)


def apply_timezone():
    """Make naive datetime.now() local to the camera."""
    os.environ['TZ'] = TZ_NAME
    time.tzset()


# ---------------------------------------------------------------- camera

CAMERA = SITE.get('camera') or {}
CAMERA_NAME = CAMERA.get('name') or 'Webcam'
CAMERA_LAT = float(CAMERA.get('lat') or 0.0)
CAMERA_LON = float(CAMERA.get('lon') or 0.0)
CAMERA_URL = get('WEBCAM_URL')
CAPTURE_INTERVAL = max(1, get_int('WEBCAM_INTERVAL', int(CAMERA.get('interval_s') or 15)))
HTTP_TIMEOUT = get_int('WEBCAM_HTTP_TIMEOUT', 8)
# Stop saving frames when the disk is this close to full; the videos and the
# rest of the machine matter more than the next picture.
MIN_FREE_GB = get_int('WEBCAM_MIN_FREE_GB', 5)

# ---------------------------------------------------------------- daylight
# "civil": from civil dawn to civil dusk (sun 6 degrees below the horizon,
# about the limit of "light enough to see"). "sun": from sunrise to sunset.
# margin_min is added at both ends.

DAYLIGHT = SITE.get('daylight') or {}
DAYLIGHT_MODE = (get('WEBCAM_DAYLIGHT_MODE') or DAYLIGHT.get('mode') or 'civil').lower()
DAYLIGHT_MARGIN_MIN = get_int('WEBCAM_DAYLIGHT_MARGIN_MIN', int(DAYLIGHT.get('margin_min') or 0))

# ---------------------------------------------------------------- video

VIDEO = SITE.get('video') or {}
VIDEO_PREFIX = VIDEO.get('prefix') or 'timelapse'
FRAMERATE = int(VIDEO.get('framerate') or 30)
CRF = str(VIDEO.get('crf') or 23)
PRESET = VIDEO.get('preset') or 'medium'
MIN_FRAMES = int(VIDEO.get('min_frames') or 10)
VIDEO_COMMENT = VIDEO.get('comment') or ''
RENDER_TIMEOUT = get_int('WEBCAM_RENDER_TIMEOUT', 1200)
# How many threads ffmpeg may use. Match the container's CPU limit: left to
# itself ffmpeg starts one per core of the HOST, and inside a 2-core limit on
# a 12-core machine that made a day's video take 150 s instead of 26.
FFMPEG_THREADS = max(1, get_int('WEBCAM_FFMPEG_THREADS', 4))
# Wait this long after the daylight window closes before making the video,
# so the last frames have landed.
RENDER_GRACE_MIN = get_int('WEBCAM_RENDER_GRACE_MIN', 10)
# After a restart, days this far back that have frames but no video are made.
CATCH_UP_DAYS = get_int('WEBCAM_CATCH_UP_DAYS', 3)
MAX_RENDER_TRIES = 3


def video_name(day):
    return f'{VIDEO_PREFIX}_{day:%Y%m%d}.mp4'


def video_file(day):
    return os.path.join(VIDEO_DIR, video_name(day))


# ---------------------------------------------------------------- clean-up

RETENTION_DAYS = max(2, get_int('WEBCAM_RETENTION_DAYS', int(SITE.get('retention_days') or 30)))
CLEANUP_DRY_RUN = get_flag('WEBCAM_CLEANUP_DRY_RUN')

# ---------------------------------------------------------------- public addresses
# Used only to write links: in the index the pages read and on share pages.

PUBLIC = SITE.get('public') or {}
PUBLIC_BASE_URL = (PUBLIC.get('base_url') or '').rstrip('/')
PUBLIC_VIDEO_PATH = PUBLIC.get('video_path') or '/'
PUBLIC_SHARE_PATH = PUBLIC.get('share_path') or '/'
PUBLIC_OG_IMAGE = PUBLIC.get('og_image') or ''
PUBLIC_BACK_LINK = PUBLIC.get('back_link') or '/'
