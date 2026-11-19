#!/usr/bin/env python3
"""The container's main loop.

Two things run here and neither waits for the other:

- The capture thread (capture.py) fetches a frame on a steady beat.
- This loop wakes once a second and starts whatever job is due, each as its
  own Python process: the video maker, the clean-up, the backup.

Rules the loop keeps:
- A job that is switched off (nothing configured for it) is never started and
  is listed as "off" in the status file.
- Last-run times are saved to disk, so a restart does not run the clean-up or
  the backup again before they are due.
- A failed job is tried again at its next interval, never in a tight loop.
- The status file and the heartbeat are written whether or not the camera
  answers. This loop being alive says nothing about the camera, and the
  camera being down does not stop this loop.
"""

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime

import capture
import index_db
import settings

settings.apply_timezone()

APP_DIR = os.path.dirname(os.path.realpath(__file__))
STATE_FILE = settings.data_path('.webcam_scheduler.json')
HEARTBEAT_FILE = settings.data_path('.webcam_heartbeat')
JOB_TIMEOUT = settings.RENDER_TIMEOUT + 300
# The camera is called "down" after this many beats in a row with no frame.
DOWN_AFTER_MISSES = 4

# name, seconds between runs, script, is it switched on
JOBS = (
    ('video', settings.get_int('WEBCAM_RENDER_CHECK_INTERVAL', 300),
     'render.py', lambda: True),
    ('cleanup', settings.get_int('WEBCAM_CLEANUP_INTERVAL', 86400),
     'cleanup.py', lambda: True),
    ('backup', settings.get_int('WEBCAM_BACKUP_INTERVAL', 86400),
     'backup.py', lambda: bool(settings.BACKUP_DIR)),
)

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True


def log(message):
    print(f'[{datetime.now(settings.TZ):%Y-%m-%d %H:%M:%S %Z}] {message}', flush=True)


def public(message):
    """A message that is safe to publish: the status file may be served to
    the web, so addresses are removed."""
    return re.sub(r'\b\w+://\S+', '(address hidden)', str(message))[:300]


def load_json(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def beat():
    """Tell the health check the loop is alive."""
    try:
        with open(HEARTBEAT_FILE, 'w') as fh:
            fh.write(str(int(time.time())))
    except OSError as exc:
        log(f'could not write the heartbeat: {exc}')


def camera_status(capturer):
    if capturer is None:
        return {'name': settings.CAMERA_NAME, 'state': 'off'}
    snap = capturer.snapshot()
    if snap['misses_in_a_row'] >= DOWN_AFTER_MISSES:
        state = 'down'
    elif snap['last_frame']:
        state = 'up'
    else:
        state = 'unknown'           # just started; no beat yet
    return {
        'name': settings.CAMERA_NAME,
        'state': state,
        'interval_s': settings.CAPTURE_INTERVAL,
        'last_frame': snap['last_frame'],
        'frames_today': snap['saved_today'],
        'missed_today': snap['missed_today'],
        'misses_in_a_row': snap['misses_in_a_row'],
        'last_problem': public(snap['last_problem']) if snap['last_problem'] else None,
        'last_problem_at': snap['last_problem_at'],
    }


def latest_video():
    try:
        conn = index_db.connect()
        try:
            row = index_db.latest(conn)
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    return {'date': row['day'], 'filename': row['filename'],
            'frames': row['image_count'], 'generated_at': row['generated_at']}


def write_status(capturer, jobs):
    try:
        write_json(settings.STATUS_FILE, {
            'updated': datetime.now(settings.TZ).isoformat(timespec='seconds'),
            'camera': camera_status(capturer),
            'latest_video': latest_video(),
            'jobs': jobs})
    except OSError as exc:
        log(f'could not write status: {exc}')


def run_script(script, capturer, jobs):
    """Run one job. Returns (ok, one-line message). The heartbeat and the
    status file keep going while it runs, so a long video is not mistaken for
    a dead loop."""
    proc = subprocess.Popen(
        [sys.executable, os.path.join(APP_DIR, script)], cwd=APP_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + JOB_TIMEOUT
    output, timed_out = None, False
    while output is None:
        try:
            output, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            beat()
            write_status(capturer, jobs)
            if time.time() > deadline or _stop:
                proc.kill()
                output, _ = proc.communicate()
                timed_out = True
    output = (output or '').strip()
    if output:
        print(output, flush=True)
    if timed_out:
        return False, f'{script} was stopped after {int(time.time() - deadline + JOB_TIMEOUT)} s'
    last_line = output.splitlines()[-1].strip() if output else ''
    if proc.returncode != 0:
        return False, last_line or f'{script} exited {proc.returncode} (see the container log)'
    return True, last_line or 'nothing to do'


def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    os.makedirs(settings.DATA_DIR, exist_ok=True)

    log(f'webcam timelapse starting; site file {settings.SITE_FILE}, '
        f'time zone {settings.TZ_NAME}, camera "{settings.CAMERA_NAME}", '
        f'daylight by {settings.DAYLIGHT_MODE}'
        + (f' +{settings.DAYLIGHT_MARGIN_MIN} min' if settings.DAYLIGHT_MARGIN_MIN else '')
        + f', frames kept {settings.RETENTION_DAYS} days'
        + (' (clean-up is a DRY RUN)' if settings.CLEANUP_DRY_RUN else ''))

    capturer = None
    if settings.CAMERA_URL:
        capturer = capture.Capturer()
        capturer.start()
        log(f'  capture: every {settings.CAPTURE_INTERVAL} s')
    else:
        log('  capture: off (WEBCAM_URL is not set)')

    state = load_json(STATE_FILE)
    jobs = {}
    for name, interval, _, enabled in JOBS:
        on = enabled()
        jobs[name] = {'state': 'waiting' if on else 'off', 'interval_s': interval}
        log(f'  {name}: ' + (f'every {interval} s' if on else 'off (not configured)'))

    while not _stop:
        if capturer is not None and not capturer.is_alive():
            log('the capture thread stopped; starting it again')
            capturer = capture.Capturer()
            capturer.start()
        now = time.time()
        for name, interval, script, enabled in JOBS:
            if _stop or not enabled():
                continue
            since = now - float(state.get(name) or 0)
            if 0 <= since < interval:
                continue                # (a clock set backwards counts as due)
            started = time.time()
            try:
                ok, message = run_script(script, capturer, jobs)
            except Exception as exc:        # a job must never stop the loop
                ok, message = False, f'{type(exc).__name__}: {exc}'
            if not ok:
                log(f'{name} FAILED: {message}')
            state[name] = started
            jobs[name] = {
                'state': 'ok' if ok else 'failed',
                'interval_s': interval,
                'last_run': datetime.fromtimestamp(started, settings.TZ).isoformat(timespec='seconds'),
                'took_s': round(time.time() - started, 1),
                'message': public(message),
            }
            try:
                write_json(STATE_FILE, state)
            except OSError as exc:
                log(f'could not save scheduler state: {exc}')
        write_status(capturer, jobs)
        beat()
        time.sleep(1)

    if capturer is not None:
        capturer.stop()
    log('stopping')
    return 0


if __name__ == '__main__':
    sys.exit(main())
