FROM python:3.12-slim

# ffmpeg turns the day's frames into the video
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a code change does not reinstall them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEBCAM_DATA_DIR=/data \
    WEBCAM_CONFIG_DIR=/config \
    WEBCAM_FRAMES_DIR=/frames \
    WEBCAM_VIDEO_DIR=/videos

# Everything below is mounted from the host at run time
RUN mkdir -p /data /config /frames /videos /share /backups \
 && chmod 777 /data /frames /videos /share /backups

# Healthy = the main loop is alive (see app/healthcheck.py)
HEALTHCHECK --interval=1m --timeout=10s --start-period=1m --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

CMD ["python", "/app/run.py"]
