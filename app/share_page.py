"""One small HTML page per video, for sharing a day.

The page comes from a template (share_page.html in the config folder; the
example beside it is the default). Words in double braces are filled in:

    {{title}} {{description}} {{date}} {{page_url}} {{video_url}}
    {{video_path}} {{og_image}} {{back_link}} {{camera}}

Every value is escaped before it goes in. Off unless WEBCAM_SHARE_DIR is set
and a template exists.
"""

import html
import os

import settings


def values(day, image_count):
    shown = f'{day:%B %d, %Y}'
    name = settings.video_name(day)
    base = settings.PUBLIC_BASE_URL
    og = settings.PUBLIC_OG_IMAGE
    return {
        'camera': settings.CAMERA_NAME,
        'date': shown,
        'title': f'{settings.CAMERA_NAME} Timelapse - {shown}',
        'description': (f'Watch all of {shown} at {settings.CAMERA_NAME} condensed into '
                        f'seconds. {image_count:,} frames.'),
        'page_url': f'{base}{settings.PUBLIC_SHARE_PATH}{day:%Y-%m-%d}.html',
        'video_path': settings.PUBLIC_VIDEO_PATH + name,
        'video_url': f'{base}{settings.PUBLIC_VIDEO_PATH}{name}',
        'og_image': og if og.startswith('http') else base + og,
        'back_link': settings.PUBLIC_BACK_LINK,
    }


def fill(template, vals):
    for key, value in vals.items():
        template = template.replace('{{' + key + '}}', html.escape(str(value), quote=True))
    return template


def write(day, image_count):
    """Write the day's page. Returns its path, or None when share pages are off."""
    if not settings.SHARE_DIR or not settings.SHARE_TEMPLATE:
        return None
    with open(settings.SHARE_TEMPLATE) as fh:
        page = fill(fh.read(), values(day, image_count))
    os.makedirs(settings.SHARE_DIR, exist_ok=True)
    path = os.path.join(settings.SHARE_DIR, f'{day:%Y-%m-%d}.html')
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        fh.write(page)
    os.replace(tmp, path)
    return path
