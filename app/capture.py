"""Fetch one picture from the camera on a steady beat and file it.

One thread, started by run.py. It wakes on every multiple of the interval
(15 s by default: at :00, :15, :30 and :45), fetches once and saves the
picture under the time of that beat. A fetch that fails is not retried: the
next beat is the retry. Making the day's video never delays it.

A camera that does not answer is a camera that does not answer. The thread
keeps beating, counts the miss and says so in the status file; it never
stops, and the container stays healthy, because restarting it would not
bring the camera back.
"""

import os
import shutil
import threading
import time
from datetime import datetime

import requests

import frames
import settings

MIN_BYTES = 1024
MAX_BYTES = 50 * 1024 * 1024


def looks_like_jpeg(data):
    """A whole JPEG: right start, right end, not a stub."""
    return (isinstance(data, (bytes, bytearray)) and len(data) >= MIN_BYTES
            and data[:2] == b'\xff\xd8' and data.rstrip(b'\x00\r\n')[-2:] == b'\xff\xd9')


def fetch(url, timeout):
    """(picture bytes, None) or (None, why not). The reason never contains
    the camera's address: it ends up in a file that may be served."""
    # `timeout` in requests is per read, not for the whole answer: a camera
    # that trickles bytes could hold a beat for minutes. So read in pieces
    # against a deadline of our own.
    deadline = time.monotonic() + 2 * timeout
    try:
        response = requests.get(url, timeout=timeout, stream=True)
        try:
            pieces, size = [], 0
            for piece in response.iter_content(65536):
                pieces.append(piece)
                size += len(piece)
                if time.monotonic() > deadline:
                    return None, 'the picture took too long to arrive'
                if size > MAX_BYTES:
                    return None, 'the answer was too large to be a picture'
            content = b''.join(pieces)
        finally:
            response.close()
    except requests.exceptions.Timeout:
        return None, 'no answer in time'
    except requests.exceptions.ConnectionError:
        return None, 'could not connect'
    except requests.exceptions.RequestException as exc:
        return None, type(exc).__name__
    if response.status_code != 200:
        return None, f'camera answered {response.status_code}'
    if not looks_like_jpeg(content):
        return None, 'the answer was not a whole picture'
    return content, None


def save(data, path):
    """Write a frame so that nothing ever reads half of one: the video maker
    and anything else looking for *.jpg sees the file only once it is whole."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, '.' + os.path.basename(path) + '.tmp')
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)


def disk_is_nearly_full(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        return shutil.disk_usage(folder).free < settings.MIN_FREE_GB * 1024 ** 3
    except OSError:
        return False


class Capturer(threading.Thread):

    def __init__(self, url=None, root=None, interval=None, fetcher=fetch):
        super().__init__(name='capture', daemon=True)
        self.url = url or settings.CAMERA_URL
        self.root = root or settings.FRAMES_DIR
        self.interval = interval or settings.CAPTURE_INTERVAL
        self.fetcher = fetcher
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._day = None
        self._last_beat = None
        self._state = {'saved_today': 0, 'missed_today': 0, 'misses_in_a_row': 0,
                       'last_frame': None, 'last_problem': None, 'last_problem_at': None}

    def stop(self):
        self._halt.set()

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _roll_day(self, day):
        """Counters are per calendar day. On the first beat (and at
        midnight) start from what is already on disk for that date."""
        if day != self._day:
            self._day = day
            already = frames.count_day(self.root, day)
            with self._lock:
                self._state['saved_today'] = already
                self._state['missed_today'] = 0

    def beat(self, when):
        """One capture, filed under `when` (aware local time). Returns True
        if a frame was saved."""
        self._roll_day(when.date())
        if disk_is_nearly_full(self.root):
            data, problem = None, f'less than {settings.MIN_FREE_GB} GB free; not saving frames'
        else:
            data, problem = self.fetcher(self.url, settings.HTTP_TIMEOUT)
        if data is not None:
            try:
                save(data, frames.frame_path(self.root, when))
            except OSError as exc:
                data, problem = None, f'could not save the frame ({type(exc).__name__})'
        stamp = when.isoformat(timespec='seconds')
        with self._lock:
            if data is not None:
                self._state['saved_today'] += 1
                self._state['misses_in_a_row'] = 0
                self._state['last_frame'] = stamp
            else:
                self._state['missed_today'] += 1
                self._state['misses_in_a_row'] += 1
                self._state['last_problem'] = problem
                self._state['last_problem_at'] = stamp
        return data is not None

    def run(self):
        announced = None
        while not self._halt.is_set():
            # Sleep to the next multiple of the interval on the wall clock.
            now = time.time()
            wait = self.interval - (now % self.interval)
            if self._halt.wait(wait):
                break
            when = datetime.fromtimestamp(round(time.time()), settings.TZ)
            # A clock nudged backwards can land two wake-ups on one second;
            # the second would overwrite the first and be counted twice.
            if self._last_beat is not None and when <= self._last_beat:
                continue
            self._last_beat = when
            try:
                ok = self.beat(when)
            except Exception as exc:        # the beat must never stop
                ok = False
                with self._lock:
                    self._state['last_problem'] = f'{type(exc).__name__}'
            # Say it in the log when the camera goes away and when it returns,
            # not on every beat.
            state = 'ok' if ok else 'missing'
            if state != announced:
                problem = self.snapshot()['last_problem']
                print(f'[{when:%Y-%m-%d %H:%M:%S %Z}] camera: '
                      + ('frames arriving' if ok else f'no frame ({problem})'), flush=True)
                announced = state
