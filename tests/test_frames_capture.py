"""Filing frames and fetching them."""

import support  # noqa: F401  (must come first)

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import capture
import frames
import settings

TZ = settings.TZ


class TestFrames(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='webcam_frames_')

    def test_path_matches_the_existing_archive_layout(self):
        when = datetime(2026, 11, 19, 13, 0, 46, tzinfo=TZ)
        self.assertEqual(frames.frame_path('/frames', when),
                         '/frames/2026/11/19/13/image_20261119_130046.jpg')

    def test_time_is_read_back_from_the_name(self):
        when = datetime(2026, 11, 19, 13, 0, 46, tzinfo=TZ)
        self.assertEqual(frames.frame_time(frames.frame_path('/f', when)), when)
        for name in ('index.html', 'image_20261119.jpg', '.image_20261119_130046.jpg.tmp',
                     'image_20261340_130046.jpg'):
            self.assertIsNone(frames.frame_time(name), name)

    def test_window_past_midnight_reads_the_next_dates_folder(self):
        base = datetime(2026, 6, 20, 0, 0, tzinfo=TZ)
        inside = [base.replace(hour=5, minute=30), base.replace(hour=23, minute=59, second=45),
                  base + timedelta(days=1, minutes=1), base + timedelta(days=1, hours=1, minutes=15)]
        outside = [base.replace(hour=3), base + timedelta(days=1, hours=1, minutes=30),
                   base + timedelta(days=1, hours=6)]
        for when in inside + outside:
            support.touch_frame(self.root, when)
        got = frames.frames_between(self.root, base.replace(hour=5, minute=19),
                                    base + timedelta(days=1, hours=1, minutes=20))
        self.assertEqual(got, [frames.frame_path(self.root, w) for w in inside])

    def test_other_files_in_the_folders_are_ignored(self):
        when = datetime(2026, 11, 19, 13, 0, 0, tzinfo=TZ)
        path = support.touch_frame(self.root, when)
        folder = os.path.dirname(path)
        for name in ('.image_20261119_130015.jpg.tmp', 'notes.txt', 'index.html'):
            open(os.path.join(folder, name), 'w').close()
        self.assertEqual(frames.frames_between(self.root, when - timedelta(hours=1),
                                               when + timedelta(hours=1)), [path])
        self.assertEqual(frames.count_day(self.root, date(2026, 11, 19)), 1)

    def test_missing_folders_give_an_empty_list(self):
        when = datetime(2026, 1, 1, 12, 0, tzinfo=TZ)
        self.assertEqual(frames.frames_between(self.root, when, when + timedelta(hours=3)), [])


class TestCapture(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='webcam_capture_')

    def test_jpeg_check(self):
        self.assertTrue(capture.looks_like_jpeg(support.FAKE_JPEG))
        self.assertFalse(capture.looks_like_jpeg(b'<html>camera is starting</html>' * 100))
        self.assertFalse(capture.looks_like_jpeg(support.FAKE_JPEG[:-2]))      # cut off
        self.assertFalse(capture.looks_like_jpeg(b'\xff\xd8\xff\xd9'))          # a stub
        self.assertFalse(capture.looks_like_jpeg(None))

    def test_a_good_beat_files_the_frame_and_leaves_no_temp_file(self):
        cap = capture.Capturer(url='x', root=self.root, interval=15,
                               fetcher=lambda url, timeout: (support.FAKE_JPEG, None))
        when = datetime(2026, 11, 19, 13, 0, 45, tzinfo=TZ)
        self.assertTrue(cap.beat(when))
        folder = os.path.join(self.root, '2026', '11', '19', '13')
        self.assertEqual(os.listdir(folder), ['image_20261119_130045.jpg'])
        snap = cap.snapshot()
        self.assertEqual((snap['saved_today'], snap['missed_today'], snap['misses_in_a_row']), (1, 0, 0))
        self.assertEqual(snap['last_frame'], when.isoformat(timespec='seconds'))

    def test_misses_are_counted_and_a_frame_resets_the_run(self):
        answers = [(None, 'no answer in time'), (None, 'could not connect'), (support.FAKE_JPEG, None)]
        cap = capture.Capturer(url='x', root=self.root, interval=15,
                               fetcher=lambda url, timeout: answers.pop(0))
        when = datetime(2026, 11, 19, 13, 0, 0, tzinfo=TZ)
        self.assertFalse(cap.beat(when))
        self.assertFalse(cap.beat(when + timedelta(seconds=15)))
        self.assertEqual(cap.snapshot()['misses_in_a_row'], 2)
        self.assertEqual(cap.snapshot()['last_problem'], 'could not connect')
        self.assertTrue(cap.beat(when + timedelta(seconds=30)))
        snap = cap.snapshot()
        self.assertEqual((snap['saved_today'], snap['missed_today'], snap['misses_in_a_row']), (1, 2, 0))

    def test_counters_start_from_what_is_on_disk_and_reset_at_midnight(self):
        day = datetime(2026, 11, 19, 10, 0, 0, tzinfo=TZ)
        for i in range(3):
            support.touch_frame(self.root, day + timedelta(seconds=15 * i))
        cap = capture.Capturer(url='x', root=self.root, interval=15,
                               fetcher=lambda url, timeout: (support.FAKE_JPEG, None))
        cap.beat(day + timedelta(hours=1))
        self.assertEqual(cap.snapshot()['saved_today'], 4)
        cap.beat(day + timedelta(days=1))
        self.assertEqual(cap.snapshot()['saved_today'], 1)

    def test_a_full_disk_stops_saving_and_says_so(self):
        cap = capture.Capturer(url='x', root=self.root, interval=15,
                               fetcher=lambda url, timeout: (support.FAKE_JPEG, None))
        real = capture.disk_is_nearly_full
        capture.disk_is_nearly_full = lambda folder: True
        try:
            self.assertFalse(cap.beat(datetime(2026, 11, 19, 13, 0, 0, tzinfo=TZ)))
        finally:
            capture.disk_is_nearly_full = real
        self.assertIn('GB free', cap.snapshot()['last_problem'])
        self.assertFalse(os.path.exists(os.path.join(self.root, '2026')))

    def test_a_finished_thread_can_still_be_asked_if_it_is_alive(self):
        """Naming the stop flag `_stop` hid a method of Thread on Python
        3.12: is_alive() on a finished thread raised, and the main loop's
        "start it again" check crashed instead."""
        cap = capture.Capturer(url='x', root=self.root, interval=1,
                               fetcher=lambda url, timeout: (support.FAKE_JPEG, None))
        cap.start()
        cap.stop()
        cap.join(timeout=5)
        self.assertFalse(cap.is_alive())

    def test_fetch_reasons_never_carry_the_address(self):
        data, why = capture.fetch('http://127.0.0.1:9/secret/cam.php', 1)
        self.assertIsNone(data)
        self.assertNotIn('127.0.0.1', why)
        self.assertNotIn('secret', why)


if __name__ == '__main__':
    unittest.main()
