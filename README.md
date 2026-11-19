# webcam-timelapse

One small container that saves a picture from a webcam every 15 seconds and
turns each day's pictures into a timelapse video.

It was built for [pribiloftraffic.com](https://www.pribiloftraffic.com), which
watches a camera on St. George Island in the Bering Sea. Nothing in the code
names that camera: you describe yours in one file and put its address in
`.env`.

## What it does

| Job | When | Writes |
|---|---|---|
| Capture | every 15 s, on the clock (:00, :15, :30, :45) | `<frames>/YYYY/MM/DD/HH/image_YYYYMMDD_HHMMSS.jpg` |
| Daily video | a few minutes after the light goes | `<videos>/<prefix>_YYYYMMDD.mp4`, a share page, the index |
| Clean-up | daily | deletes frames older than 30 days, once their video exists |
| Backup | daily | a dated copy of the index database |

It also writes `webcam_status.json`: when the last frame arrived, how many were
missed today, and what each job last did.

**A day is one stretch of daylight, not midnight to midnight.** The video
covers civil dawn to civil dusk at the camera's position, worked out each day.
In winter that is a short window inside one date. In a northern summer it runs
past midnight: at 56 N the June video starts about 5:20 AM and ends about
1:20 AM the next morning. The video is named for the date the light began, and
it is made when the light ends, whatever the clock says. Dark frames are left
out.

**Every picture is in the video.** A common way to feed pictures to ffmpeg
(a `duration` line per picture) quietly drops about one in six at 30 frames a
second. This does not do that; a test counts the frames.

## What you need

- Docker with Compose.
- A camera that answers a plain HTTP request with one JPEG.
- About 1.5 GB of disk per day of frames at 1024x576 (45 GB for 30 days).

## Set it up

1. **Get the code** into a folder beside your `docker-compose.yml`, here
   called `webcam_timelapse`.

2. **Describe your camera.** Copy the example and edit it:

   ```
   cp webcam_timelapse/config/site.example.json webcam_timelapse/config/site.json
   ```

   | Key | Meaning |
   |---|---|
   | `timezone` | The camera's local zone. Frames are filed under local date and hour, so set it once and do not change it. |
   | `camera` | `name`, `lat`, `lon` (for the daylight times) and `interval_s`. |
   | `daylight` | `mode`: `civil` (dawn to dusk) or `sun` (sunrise to sunset). `margin_min`: minutes added at both ends. |
   | `video` | `prefix` of the file name, `framerate`, `crf` (quality, lower is better), `preset`, `min_frames`, `comment`. |
   | `retention_days` | Days of frames to keep. |
   | `public` | Optional. Where the videos and share pages are served, used only to write links: `base_url`, `video_path`, `share_path`, `og_image`, `back_link`. |

3. **Add the settings.** Copy the lines you need from `.env.example` into the
   `.env` beside your compose file.

4. **Add the service** to your `docker-compose.yml`:

   ```yaml
   services:
     webcam-timelapse:
       build: ./webcam_timelapse
       container_name: webcam-timelapse
       restart: always
       user: "${WEBCAM_UID}:${WEBCAM_GID}"
       environment:
         - WEBCAM_URL=${WEBCAM_URL}
         - WEBCAM_FFMPEG_THREADS=${WEBCAM_FFMPEG_THREADS:-4}
         - WEBCAM_RETENTION_DAYS=${WEBCAM_RETENTION_DAYS:-30}
         - WEBCAM_CLEANUP_DRY_RUN=${WEBCAM_CLEANUP_DRY_RUN:-}
         - WEBCAM_BACKUP_KEEP=${WEBCAM_BACKUP_KEEP:-3}
         - WEBCAM_SHARE_DIR=${WEBCAM_SHARE_DIR:+/share}
         - WEBCAM_BACKUP_DIR=${WEBCAM_BACKUP_DIR:+/backups}
       volumes:
         - ${WEBCAM_DATA_DIR}:/data
         - ${WEBCAM_CONFIG_DIR}:/config:ro
         - ${WEBCAM_FRAMES_DIR}:/frames
         - ${WEBCAM_VIDEO_DIR}:/videos
         - ${WEBCAM_SHARE_DIR:-./webcam_timelapse/share}:/share
         - ${WEBCAM_BACKUP_DIR:-./webcam_timelapse/backups}:/backups
       mem_limit: 1g
       cpus: 4
   ```

5. **Start it and look.**

   ```
   docker compose up -d --build webcam-timelapse
   docker compose logs -f webcam-timelapse
   ```

   The first lines list every job. Within 15 seconds you should see
   `camera: frames arriving`.

   If the frames or videos folder belongs to a group the container's user is
   not in (a web server's group, say), add that group's number to the
   service: `group_add: ["33"]`. Without it nothing can be written, and the
   status file says `could not save the frame`.

## Checking it is working

- `docker ps` shows the container as `healthy`. Healthy means the main loop is
  running. It stays healthy when the camera is down, because restarting the
  container would not bring the camera back.
- `data/webcam_status.json`: `camera.state` is `up`, `down` (a minute with no
  frame), `unknown` (just started) or `off`. `last_problem` says why a frame
  was missed, without the camera's address.
- The log says once when the camera goes away and once when it comes back, not
  every 15 seconds.

## By hand

```
docker exec webcam-timelapse python /app/render.py --day 2026-06-20 --dry-run
docker exec webcam-timelapse python /app/render.py --day 2026-06-20
docker exec webcam-timelapse python /app/cleanup.py --dry-run
```

The first says which stretch of time a day covers and how many frames it has.
The second makes (or remakes) that day's video.

## The index the web pages read

`data/timelapse_metadata.json` lists every video: `type` (always `daily`),
`date`, `filename`, `path` (the public path), `image_count`,
`duration_seconds`, `size_mb`, `generated_at`. It is written from the database
(`data/timelapse.db`) after every video, so the JSON file can be lost or torn
without losing anything.

To carry over videos made by an earlier setup, put its index in the data folder
as `timelapse_metadata.legacy.json` before the first start. Daily videos whose
file is really in the video folder are taken; everything else is ignored.

## Share pages

Each video gets a small HTML page with social-preview tags, written from
`config/share_page.html` (falling back to `share_page.example.html`). Words in
double braces are filled in: `{{title}}`, `{{description}}`, `{{date}}`,
`{{camera}}`, `{{page_url}}`, `{{video_url}}`, `{{video_path}}`,
`{{og_image}}`, `{{back_link}}`. Off unless `WEBCAM_SHARE_DIR` is set.

## Speed

ffmpeg starts one thread per core of the host, not of the container. Inside a
2-core limit on a 12-core machine a day's video took 150 seconds; with
`cpus: 4` and `WEBCAM_FFMPEG_THREADS=4` it takes 26. Keep the two numbers the
same.

## Things to know

- **The clean-up never deletes a day that has no video.** Without the video
  those frames are the only copy of the day. Such days are named in the log.
- **Only folders shaped `YYYY/MM/DD` are ever deleted.** Other files in the
  frames folder are left alone.
- **A missed frame is not retried.** The next beat, 15 seconds later, is the
  retry.
- **A day with too few frames** (camera down all day) gets no video. It is
  tried three times, an hour apart, then left.
- **After a restart** the last three days are checked and any missing video is
  made, as long as the frames are still there.
- **Capture stops when the disk has under 5 GB free**, and the status file
  says so.

## How the original site is wired up

On pribiloftraffic.com:

- **The camera is on an island; the server is somewhere else.** They are
  joined by [ZeroTier](https://www.zerotier.com/), a private network, and
  `WEBCAM_URL` is the camera's ZeroTier address.
- **nginx serves the website** as plain files. The frames, videos and share
  pages folders are inside the site's own folder, so the videos are served
  the moment they are written. The index is linked into the site's data
  folder.
- **nginx also reverse-proxies the live camera picture** under a path on the
  site, because a visitor's browser cannot reach a private address. That is
  for the live view; this container does not need it.
- **Cloudflare sits in front** for HTTPS and caching.

None of this is required. The container only needs an address it can reach
and a folder to write to.

- **Any private network will do in place of ZeroTier:** Tailscale, NetBird,
  Headscale or plain WireGuard. Docker containers go out through the host, so
  whatever the host can reach, the container can reach. With Tailscale, put
  the device's `100.x.x.x` address in `.env`; its device names often do not
  resolve inside a container.
- **Any web server will do in place of nginx.** It only has to serve the
  files in the data folder. Nothing here needs to be proxied.

## Tests

```
python3 -m unittest discover -s tests
```

49 tests. They need `astral` (see `requirements.txt`); the ones that make a
real video are skipped where ffmpeg is not installed.

## Where this came from

The idea is older than the AI help. It began years ago as a hand-written script that saved pictures from a
Raspberry Pi camera on St. George Island and stitched them into a video of
the day.
It was written and run that way, without AI, long before any was involved.

AI came later, as an assistant. Claude helped tidy the code, add tests, find
bugs and package it as a container other people can run. The ideas, and the
judgement about what matters on these islands, are the maintainer's own.

Most of the Pribilof Traffic collectors started on Raspberry Pis, and
Raspberry Pis on the islands still run the webcam and the aircraft (tar1090)
and ACARS receivers today.

## Licence

MIT. See `LICENSE`.
