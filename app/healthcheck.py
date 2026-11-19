#!/usr/bin/env python3
"""Container health check.

Healthy means the main loop is alive: it rewrote its heartbeat file within the
last two minutes. The loop writes the heartbeat on every pass whether or not
the camera answered, so a camera outage does not make the container
unhealthy (restarting it would not help). Whether frames are arriving, and
what each job last did, is in webcam_status.json in the data folder.

Exit code 0 = healthy, 1 = unhealthy.
"""

import os
import sys
import time

import settings

HEARTBEAT = settings.data_path('.webcam_heartbeat')
MAX_AGE = 120

try:
    age = time.time() - os.path.getmtime(HEARTBEAT)
except OSError as exc:
    print(f'unhealthy: no heartbeat ({exc})')
    sys.exit(1)
if age > MAX_AGE:
    print(f'unhealthy: main loop last ran {int(age)} s ago')
    sys.exit(1)
print(f'healthy: main loop ran {int(age)} s ago')
sys.exit(0)
