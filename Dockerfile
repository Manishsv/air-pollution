# AirOS Core — packaging only. No secrets. Default entry is a safe health check.
# Build: docker build -t air-os:local .

FROM python:3.11-slim-bookworm

# Geo stack (geopandas/fiona/osmnx), optional GDAL-bound builds, and headless OpenCV deps.
# Mirrors CI intent in .github/workflows/ci.yml.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    proj-bin \
    proj-data \
    libspatialindex-dev \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.txt is copied first for transparency and cache alignment with local installs.
# The image installs from requirements-docker.txt (same stack minus optional YOLO/torch).
COPY requirements.txt requirements-docker.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-docker.txt \
    && python -m pip install --no-cache-dir pytest

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Friendly CLI entrypoint:
#   docker run --rm ghcr.io/manishsv/air-os:latest doctor
#   docker run --rm ghcr.io/manishsv/air-os:latest conformance
#   docker run --rm ghcr.io/manishsv/air-os:latest deployment run deployments/examples/flood_local_demo
ENTRYPOINT ["python", "tools/airos_cli.py"]

# Safe default: lightweight doctor (prints env + runs supervisor without conformance by default).
CMD ["doctor"]
