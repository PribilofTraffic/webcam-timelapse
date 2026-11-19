"""The video index, the share page and the frame clean-up."""

import support  # noqa: F401  (must come first)

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import cleanup
import index_db
import render
import settings
import share_page

TZ = settings.TZ


def memory_db():
    return index_db.connect(os.path.join(tempfile.mkdtemp(prefix='webcam_db_'), 't.db'))


class TestIndex(unittest.TestCase):

    def test_index_file_keeps_the_keys_the_pages_read(self):
        conn = memory_db()
        index_db.add_video(conn, date(2026, 11, 18), 'stg_timelapse_20261118.mp4', 2358, 78.6, 10.46,
                           '2026-11-18 19:01:02 AKST')
        index_db.add_video(conn, date(2026, 11, 17), 'stg_timelapse_20261117.mp4', 2300, 76.7, 11.3,
                           '2026-11-17 19:02:00 AKST')
        payload = index_db.index_payload(conn, datetime(2026, 11, 18, 19, 5, tzinfo=TZ))
        self.assertEqual([t['date'] for t in payload['timelapses']], ['2026-11-17', '2026-11-18'])
        last = payload['timelapses'][-1]
        self.assertEqual(set(last), {'type', 'date', 'filename', 'path', 'image_count',
                                     'duration_seconds', 'size_mb', 'generated_at'})
        self.assertEqual(last['type'], 'daily')
        self.assertEqual(last['path'], '/timelapsestg/videos/daily/stg_timelapse_20261118.mp4')
        self.assertTrue(payload['last_updated'].endswith('AKST'))

    def test_remaking_a_day_replaces_its_row(self):
        conn = memory_db()
        for count in (100, 200):
            index_db.add_video(conn, date(2026, 11, 18), 'a.mp4', count, 1, 1, 'x')
        payload = index_db.index_payload(conn, datetime.now(TZ))
        self.assertEqual([t['image_count'] for t in payload['timelapses']], [200])

    def test_legacy_import_takes_only_daily_videos_that_exist(self):
        folder = tempfile.mkdtemp(prefix='webcam_legacy_')
        videos = os.path.join(folder, 'videos')
        os.makedirs(videos)
        open(os.path.join(videos, 'stg_timelapse_20261117.mp4'), 'w').close()
        legacy = os.path.join(folder, 'old.json')
        with open(legacy, 'w') as fh:
            json.dump({'timelapses': [
                {'type': 'daily', 'date': '2026-11-17', 'filename': 'stg_timelapse_20261117.mp4',
                 'path': '/var/www/x/stg_timelapse_20261117.mp4', 'image_count': 2300,
                 'duration_seconds': 76.6, 'size_mb': 11.3, 'generated_at': '2026-11-17 21:00:19 '},
                {'type': 'daily', 'date': '2026-11-16', 'filename': 'stg_timelapse_20261116.mp4',
                 'image_count': 1, 'duration_seconds': 1, 'size_mb': 1, 'generated_at': 'x'},
                {'type': 'weekly', 'start_date': '2025-10-19', 'filename': 'stg_timelapse_week_20251025.mp4'},
                {'type': 'monthly', 'filename': 'stg_timelapse_month_202510.mp4'},
                {'type': 'daily', 'date': 'not a date', 'filename': '../../etc/passwd'},
                'junk',
            ]}, fh)
        conn = memory_db()
        self.assertEqual(index_db.import_legacy(conn, legacy, videos), 1)
        self.assertEqual(index_db.video_days(conn), {date(2026, 11, 17)})
        self.assertEqual(index_db.latest(conn)['generated_at'], '2026-11-17 21:00:19')
        # Only an EMPTY database is seeded.
        self.assertEqual(index_db.import_legacy(conn, legacy, videos), 0)

    def test_a_day_that_cannot_be_made_is_retried_a_few_times_then_left(self):
        conn = memory_db()
        now = datetime(2026, 12, 21, 21, 0, tzinfo=TZ)
        day = date(2026, 12, 21)
        self.assertIn(day, render.due_days(conn, now))
        index_db.note_attempt(conn, day, '0 frames', now.isoformat(timespec='seconds'))
        self.assertNotIn(day, render.due_days(conn, now + timedelta(minutes=30)))
        self.assertIn(day, render.due_days(conn, now + timedelta(minutes=61)))
        for _ in range(2):
            index_db.note_attempt(conn, day, '0 frames', now.isoformat(timespec='seconds'))
        self.assertNotIn(day, render.due_days(conn, now + timedelta(hours=3)))
        # ...and a video clears the slate.
        index_db.add_video(conn, day, 'a.mp4', 10, 1, 1, 'x')
        self.assertIsNone(index_db.attempt(conn, day))
        self.assertNotIn(day, render.due_days(conn, now + timedelta(hours=3)))


class TestSharePage(unittest.TestCase):

    def test_values_are_filled_and_escaped(self):
        vals = share_page.values(date(2026, 11, 18), 2358)
        self.assertEqual(vals['page_url'], 'https://www.pribiloftraffic.com/timelapsestg/daily/2026-11-18.html')
        self.assertEqual(vals['video_path'], '/timelapsestg/videos/daily/stg_timelapse_20261118.mp4')
        self.assertEqual(vals['og_image'], 'https://www.pribiloftraffic.com/images/DSCN2082.JPG')
        page = share_page.fill('<title>{{title}}</title><a href="{{back_link}}">',
                               {'title': 'A <b>"day"</b>', 'back_link': '/x/'})
        self.assertEqual(page, '<title>A &lt;b&gt;&quot;day&quot;&lt;/b&gt;</title><a href="/x/">')

    def test_page_is_written_with_nothing_left_unfilled(self):
        path = share_page.write(date(2026, 11, 18), 2358)
        self.assertTrue(path.endswith('2026-11-18.html'))
        page = open(path).read()
        self.assertNotIn('{{', page)
        self.assertIn('2,358 frames', page)
        self.assertIn('stg_timelapse_20261118.mp4', page)


class TestCleanup(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='webcam_clean_')
        self.today = date(2026, 11, 19)

    def day(self, back, frames=2):
        d = self.today - timedelta(days=back)
        for i in range(frames):
            support.touch_frame(self.root, datetime(d.year, d.month, d.day, 12, 0, i, tzinfo=TZ))
        return d

    def folder(self, d):
        return os.path.join(self.root, f'{d:%Y}', f'{d:%m}', f'{d:%d}')

    def test_old_days_with_a_video_go_and_recent_days_stay(self):
        old, older, recent = self.day(31), self.day(32), self.day(5)
        summary = cleanup.clean(self.root, self.today, lambda d: True, retain_days=30)
        self.assertEqual(summary['removed'], [str(older), str(old)])
        self.assertFalse(os.path.exists(self.folder(old)))
        self.assertTrue(os.path.exists(self.folder(recent)))
        self.assertEqual(summary['days_kept'], 1)

    def test_the_cutoff_day_itself_is_kept(self):
        edge = self.day(30)
        summary = cleanup.clean(self.root, self.today, lambda d: True, retain_days=30)
        self.assertEqual(summary['removed'], [])
        self.assertTrue(os.path.exists(self.folder(edge)))

    def test_a_day_with_no_video_is_kept_and_named(self):
        old = self.day(40)
        summary = cleanup.clean(self.root, self.today, lambda d: False, retain_days=30)
        self.assertEqual(summary['removed'], [])
        self.assertEqual(summary['waiting_for_video'], [str(old)])
        self.assertTrue(os.path.exists(self.folder(old)))

    def test_a_day_is_kept_while_the_day_before_still_needs_its_frames(self):
        """A summer video runs past midnight: the first hours of the 21st's
        folder belong to the 20th's video."""
        twentieth, twentyfirst = self.day(41), self.day(40)
        have = {twentyfirst}
        summary = cleanup.clean(self.root, self.today, lambda d: d in have, retain_days=30)
        self.assertEqual(summary['removed'], [])
        self.assertEqual(summary['waiting_for_video'], [str(twentieth), str(twentyfirst)])
        have.add(twentieth)
        summary = cleanup.clean(self.root, self.today, lambda d: d in have, retain_days=30)
        self.assertEqual(summary['removed'], [str(twentieth), str(twentyfirst)])

    def test_dry_run_deletes_nothing(self):
        old = self.day(40)
        summary = cleanup.clean(self.root, self.today, lambda d: True, retain_days=30, dry_run=True)
        self.assertEqual(summary['removed'], [str(old)])
        self.assertTrue(os.path.exists(self.folder(old)))

    def test_only_date_shaped_folders_are_touched(self):
        """The live archive folder also holds a web page."""
        old = self.day(40)
        open(os.path.join(self.root, 'index.html'), 'w').close()
        os.makedirs(os.path.join(self.root, 'videos', 'daily'))
        os.makedirs(os.path.join(self.root, '2026', 'notes'))
        outside = tempfile.mkdtemp(prefix='webcam_outside_')
        open(os.path.join(outside, 'keep.txt'), 'w').close()
        os.symlink(outside, os.path.join(self.root, '2024'))
        cleanup.clean(self.root, self.today, lambda d: True, retain_days=30)
        self.assertFalse(os.path.exists(self.folder(old)))
        self.assertTrue(os.path.isfile(os.path.join(self.root, 'index.html')))
        self.assertTrue(os.path.isdir(os.path.join(self.root, 'videos', 'daily')))
        self.assertTrue(os.path.isdir(os.path.join(self.root, '2026', 'notes')))
        self.assertTrue(os.path.isfile(os.path.join(outside, 'keep.txt')))

    def test_empty_month_and_year_folders_are_tidied(self):
        d = date(2025, 12, 31)
        support.touch_frame(self.root, datetime(2025, 12, 31, 12, 0, 0, tzinfo=TZ))
        self.day(3)
        cleanup.clean(self.root, self.today, lambda day: True, retain_days=30)
        self.assertFalse(os.path.exists(os.path.join(self.root, '2025')))
        self.assertTrue(os.path.exists(os.path.join(self.root, '2026')))

    def test_retention_is_never_less_than_two_days(self):
        yesterday = self.day(1)
        summary = cleanup.clean(self.root, self.today, lambda d: True, retain_days=0)
        self.assertEqual(summary['removed'], [])
        self.assertTrue(os.path.exists(self.folder(yesterday)))


if __name__ == '__main__':
    unittest.main()
