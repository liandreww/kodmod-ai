# syntax=docker/dockerfile:1.7
# ============================================================================
# KODMOD AI — Production Dockerfile
# ============================================================================
# Multi-stage build:
#   1. `builder`  — installs deps into a venv (cacheable layer)
#   2. `runtime`  — slim final image with the venv copied in
#
# CPU-only image by default. For GPU inference (faster-whisper on cuda),
# build the variant with `--build-arg BASE_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04`
# and add torch with the matching cuda wheel.
# ============================================================================

ARG BASE_IMAGE=python:3.11-slim-bookworm
ARG APP_USER=kodmod
ARG APP_UID=1001

# ------------------------------------------------------------------- builder --
FROM ${BASE_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Create the virtual environment once; pip caches into here.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the dep manifests first to maximise layer cache hits.
COPY pyproject.toml requirements.txt ./
RUN pip install --upgrade pip wheel setuptools \
 && pip install -r requirements.txt

# Now copy the source tree.
COPY . /build

# ------------------------------------------------------------------ runtime --
FROM ${BASE_IMAGE} AS runtime

ARG APP_USER
ARG APP_UID

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/${APP_USER}

# Runtime deps only.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u ${APP_UID} -m -s /bin/bash ${APP_USER}

# Bring in the venv from the builder.
COPY --from=builder /opt/venv /opt/venv

# Bring in the application code.
WORKDIR /app
COPY --from=builder /build /app

# Writable mount points for audio + uploads.
RUN mkdir -p /var/lib/kodmod/audio /var/lib/kodmod/uploads \
 && chown -R ${APP_USER}:${APP_USER} /var/lib/kodmod /app

USER ${APP_USER}

EXPOSE 8000

# Healthcheck hits the readiness endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# tini is PID 1 so SIGTERM propagates cleanly to uvicorn.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command — use --workers 1 inside k8s and scale via replicas.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-config", "/app/docker/log_conf.json"]
