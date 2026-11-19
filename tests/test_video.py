"""Making a real video from real pictures (skipped where ffmpeg is missing)."""

import support  # noqa: F401  (must come first)

import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta

import frames
import index_db
import render
import settings
import video

TZ = settings.TZ
HAVE_FFMPEG = shutil.which('ffmpeg') is not None


class TestCommand(unittest.TestCase):

    def test_list_file_names_each_frame_once_and_quotes_paths(self):
        folder = tempfile.mkdtemp(prefix='webcam_list_')
        listing = os.path.join(folder, 'l.txt')
        video.write_list(["/a/it's.jpg", '/a/b.jpg'], listing)
        self.assertEqual(open(listing).read().splitlines(),
                         ["file '/a/it'\\''s.jpg'", "file '/a/b.jpg'"])

    def test_command_gives_every_picture_exactly_one_frame(self):
        cmd = video.command('l.txt', 'o.mp4', 'T')
        self.assertIn('setpts=N/(30*TB)', cmd)
        self.assertEqual(cmd[cmd.index('-r') + 1], '30')
        self.assertNotIn('-vsync', cmd)
        self.assertEqual(cmd[cmd.index('-threads') + 1], '4')
        self.assertEqual(cmd[-2:], ['-y', 'o.mp4'])

    def test_no_frames_is_a_plain_failure(self):
        self.assertEqual(video.render([], '/nowhere/x.mp4', 't'), (False, 'no frames'))


@unittest.skipUnless(HAVE_FFMPEG, 'ffmpeg is not installed here')
class TestRealVideo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Twenty real JPEGs, drawn by ffmpeg itself."""
        cls.pictures = tempfile.mkdtemp(prefix='webcam_pics_')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'testsrc=size=320x180:rate=1', '-frames:v', '20',
                        os.path.join(cls.pictures, 'p%02d.jpg')], check=True)

    def picture(self, i):
        with open(os.path.join(self.pictures, f'p{i % 20 + 1:02d}.jpg'), 'rb') as fh:
            return fh.read()

    def test_render_writes_a_playable_file_and_cleans_up(self):
        folder = tempfile.mkdtemp(prefix='webcam_out_')
        output = os.path.join(folder, 'day.mp4')
        ok, message = video.render(sorted(os.path.join(self.pictures, n)
                                          for n in os.listdir(self.pictures)), output, 'A day')
        self.assertTrue(ok, message)
        self.assertEqual(os.listdir(folder), ['day.mp4'])
        probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                '-show_entries', 'stream=nb_read_frames,codec_name', '-of',
                                'default=nw=1', output], capture_output=True, text=True)
        self.assertIn('codec_name=h264', probe.stdout)
        # Every picture is in the video. (Listing a duration per picture, as
        # the cron script did, gives 19 here and loses 1 in 6 on a real day.)
        self.assertIn('nb_read_frames=20', probe.stdout)

    def test_a_failed_render_leaves_the_old_video_alone(self):
        folder = tempfile.mkdtemp(prefix='webcam_out_')
        output = os.path.join(folder, 'day.mp4')
        with open(output, 'w') as fh:
            fh.write('yesterday')
        ok, message = video.render([os.path.join(folder, 'missing.jpg')], output, 'A day')
        self.assertFalse(ok)
        self.assertIn('ffmpeg', message)
        self.assertEqual(open(output).read(), 'yesterday')
        self.assertEqual(os.listdir(folder), ['day.mp4'])

    def test_a_june_day_is_made_from_two_date_folders(self):
        """End to end: frames either side of midnight become one video named
        for the day the light began, and the index and share page follow."""
        day = date(2026, 6, 20)
        base = datetime(2026, 6, 20, 0, 0, tzinfo=TZ)
        wanted = [base.replace(hour=12) + timedelta(seconds=15 * i) for i in range(8)]
        wanted += [base + timedelta(days=1, minutes=30) + timedelta(seconds=15 * i) for i in range(6)]
        dark = [base.replace(hour=3), base + timedelta(days=1, hours=3)]
        for i, when in enumerate(wanted + dark):
            support.touch_frame(settings.RENDER_FROM_DIR, when, self.picture(i))
        conn = index_db.connect()
        try:
            ok, message = render.make(conn, day, datetime(2026, 6, 21, 3, 0, tzinfo=TZ))
            self.assertTrue(ok, message)
            self.assertIn('14 frames', message)
            self.assertIn('next day', message)
            row = index_db.latest(conn)
        finally:
            conn.close()
        self.assertEqual(row['filename'], 'stg_timelapse_20260620.mp4')
        self.assertEqual(row['image_count'], 14)
        self.assertTrue(row['window_end'].startswith('2026-06-21T01:'))
        self.assertTrue(os.path.isfile(settings.video_file(day)))
        self.assertTrue(os.path.isfile(os.path.join(settings.SHARE_DIR, '2026-06-20.html')))
        self.assertTrue(os.path.isfile(settings.INDEX_FILE))

    def test_too_few_frames_makes_no_video_and_is_noted(self):
        day = date(2026, 2, 2)
        support.touch_frame(settings.RENDER_FROM_DIR, datetime(2026, 2, 2, 13, 0, tzinfo=TZ), self.picture(0))
        conn = index_db.connect()
        try:
            ok, message = render.make(conn, day, datetime(2026, 2, 2, 22, 0, tzinfo=TZ))
            self.assertFalse(ok)
            self.assertIn('only 1 frames', message)
            self.assertEqual(index_db.attempt(conn, day)['tries'], 1)
        finally:
            conn.close()
        self.assertFalse(os.path.exists(settings.video_file(day)))


if __name__ == '__main__':
    unittest.main()
