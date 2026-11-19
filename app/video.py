"""Turn a list of frames into one MP4 with ffmpeg."""

import os
import subprocess

import settings


def command(list_file, output, title):
    """The ffmpeg command line. Kept separate so a test can read it."""
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0', '-i', list_file,
        # Number the pictures 0, 1, 2... and show each for exactly one frame.
        # (Giving each picture a "duration" in the list instead looks
        # equivalent and is not: ffmpeg rounds those onto a 25-a-second grid
        # and silently drops about one picture in six at 30 a second. The
        # cron script this replaces did that for a year.)
        '-vf', f'setpts=N/({settings.FRAMERATE}*TB)', '-r', str(settings.FRAMERATE),
        '-pix_fmt', 'yuv420p',              # plays everywhere
        '-c:v', 'libx264', '-crf', settings.CRF, '-preset', settings.PRESET,
        '-threads', str(settings.FFMPEG_THREADS),
        '-movflags', '+faststart',          # starts playing before it has all arrived
        '-metadata', f'title={title}',
    ]
    if settings.VIDEO_COMMENT:
        cmd += ['-metadata', f'comment={settings.VIDEO_COMMENT}']
    return cmd + ['-y', output]


def write_list(frames, list_file):
    with open(list_file, 'w') as fh:
        for path in frames:
            quoted = os.path.abspath(path).replace("'", "'\\''")
            fh.write(f"file '{quoted}'\n")


def render(frames, output, title):
    """Make `output` from `frames`. Returns (ok, message).

    ffmpeg writes to a hidden file beside the target and the result is moved
    into place only when it is complete, so a web page never plays half a
    video and a failed run leaves yesterday's file alone.
    """
    if not frames:
        return False, 'no frames'
    folder = os.path.dirname(output)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.basename(output)
    list_file = os.path.join(folder, f'.{stem}.frames.txt')
    partial = os.path.join(folder, f'.{stem}.part.mp4')
    try:
        write_list(frames, list_file)
        result = subprocess.run(command(list_file, partial, title), capture_output=True,
                                text=True, timeout=settings.RENDER_TIMEOUT)
        if result.returncode != 0:
            tail = (result.stderr or '').strip().splitlines()[-1:] or ['no message']
            return False, f'ffmpeg exited {result.returncode}: {tail[0][:200]}'
        if not os.path.isfile(partial) or os.path.getsize(partial) == 0:
            return False, 'ffmpeg wrote nothing'
        os.replace(partial, output)
        return True, 'ok'
    except subprocess.TimeoutExpired:
        return False, f'ffmpeg ran past {settings.RENDER_TIMEOUT} s and was stopped'
    except OSError as exc:
        return False, f'{type(exc).__name__}: {exc.strerror or exc}'
    finally:
        for leftover in (list_file, partial):
            try:
                os.remove(leftover)
            except OSError:
                pass
