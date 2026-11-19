"""Shared test setup: point the settings at the example site file and at
throwaway folders, before anything imports them. Every test module imports
this first."""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'app'))

TMP = tempfile.mkdtemp(prefix='webcam_test_')
os.environ['WEBCAM_ENV_FILE'] = os.path.join(HERE, 'no-such-env-file')
os.environ['WEBCAM_SITE_FILE'] = os.path.join(REPO, 'config', 'site.example.json')
os.environ['WEBCAM_SHARE_TEMPLATE'] = os.path.join(REPO, 'config', 'share_page.example.html')
for name in ('DATA', 'FRAMES', 'VIDEO', 'SHARE'):
    os.environ[f'WEBCAM_{name}_DIR'] = os.path.join(TMP, name.lower())
    os.makedirs(os.environ[f'WEBCAM_{name}_DIR'])
for name in ('WEBCAM_URL', 'WEBCAM_BACKUP_DIR', 'WEBCAM_TZ', 'WEBCAM_RENDER_FROM_DIR',
             'WEBCAM_DAYLIGHT_MODE', 'WEBCAM_DAYLIGHT_MARGIN_MIN', 'WEBCAM_CLEANUP_DRY_RUN',
             'WEBCAM_RETENTION_DAYS', 'WEBCAM_FFMPEG_THREADS', 'WEBCAM_INTERVAL', 'WEBCAM_LEGACY_INDEX', 'WEBCAM_DB_PATH'):
    os.environ.pop(name, None)

# A real (tiny) JPEG is not needed: the capture check looks at the first and
# last two bytes and the length.
FAKE_JPEG = b'\xff\xd8' + b'x' * 2000 + b'\xff\xd9'


def touch_frame(root, when, data=FAKE_JPEG):
    import frames
    path = frames.frame_path(root, when)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return path
