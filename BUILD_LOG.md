# Build log

## 2026-11-19: first build

Replaces six cron lines on the pribiloftraffic host: `webcam_archive.py`
started four times a minute (with `sleep 15/30/45`), and
`generate_timelapse.py` for the daily video and the 30-day clean-up.

What was carried over unchanged: the frame layout and names, the video file
names, the share pages, and the keys in `timelapse_metadata.json`, so an
existing archive and the pages that read the index need no change.

What is different, and why:

- **One loop, not four cron lines.** Frames land on the clock at :00, :15,
  :30, :45. Each is written to a hidden temp file and renamed, so nothing
  reads half a picture.
- **A camera day is a stretch of daylight.** The cron job made the video at
  06:00 UTC (9 PM in winter, 10 PM in summer) from one calendar date's folder.
  In June at this camera the sun sets after midnight, so the video was made
  three hours before the light ended and the dusk after midnight was in no
  video at all. Now the window follows the light into the next date's folder
  and the video is made when it closes.
- **Civil twilight, not sunrise/sunset plus an hour.** The two are close here:
  within 8 minutes in June, and civil is 15 to 20 minutes shorter at each end
  in winter. The first and last frames at civil dawn and dusk are already
  nearly dark on this camera, so nothing worth seeing is lost. Switch with
  `daylight.mode` / `margin_min`.
- **The cron videos were missing one frame in six.** The script listed a
  `duration 0.0333` per picture and used `-vsync vfr`; ffmpeg put those on a
  25-per-second grid and dropped the rest. 2026-11-18: 2358 pictures chosen,
  1967 in the video. Now `setpts=N/(30*TB) -r 30`: every picture, 30 a second.
  A test counts frames with ffprobe.
- **The sun library and midnight.** astral answers "the sunset on this date".
  Far west in a time zone that question breaks in July, when sunset drifts
  back across midnight: one local date has two sunsets and the one before has
  none. Asking in the camera's own solar time (a fixed zone from its
  longitude) puts every event well away from midnight. A test walks every day
  of the year in both modes.
- **The index is a database.** `timelapse_metadata.json` was one file,
  appended to and rewritten whole each night. It is now written from
  `timelapse.db`, which is backed up daily. Old weekly and monthly entries
  (their videos were deleted long ago) are not carried over.
- **No hourly walk of the archive.** The cron script counted and measured
  every frame (180,000 files) four times at the top of each hour. Counts are
  kept in memory; the clean-up measures the archive once a day.
- **Clean-up waits for the day before.** A folder's first hours can belong to
  the previous day's video, so a day is deleted only when the day before is
  settled too.
- **ffmpeg threads.** See README, "Speed".

Trial: `webcam-timelapse-trial`, started 2026-11-19 13:19 AKST, capturing into
a separate trial folder and making videos from the live archive
(mounted read-only), clean-up in dry-run. Its first act was to remake
2026-11-16, -17 and -18: 2288, 2276 and 2241 frames, all present in the
videos, against 2010, 1999 and 1967 in the cron ones.
