# syntax=docker/dockerfile:1
# apps/api/Dockerfile
# Zero-cost production deployment for AI Video Tutor API & Voice Worker
# Target environments:
# - Oracle Cloud Always Free ARM / x86 VM
# - Hugging Face Spaces (Docker Basic CPU)
# - Local Docker development

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    RUN_MODE=api

WORKDIR /app

# Install system dependencies:
# - ca-certificates & curl for secure networking and uv download
# - espeak-ng & libsndfile1 for Kokoro ONNX CPU audio synthesis
# - ffmpeg for media processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    espeak-ng \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv from official binary
COPY --from=ghcr.io/astral-sh/uv:0.5.21 /uv /uvx /bin/

# Copy dependency manifests first for build caching
COPY pyproject.toml uv.lock ./

# Install Python virtual environment without root project editable install
RUN uv sync --frozen --no-install-project

# Copy application source code and migrations
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# Sync final project dependencies into venv
RUN uv sync --frozen

# Expose standard web application port
EXPOSE 8000 7860

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Entrypoint script supporting RUN_MODE:
# - "api" (default): runs FastAPI uvicorn server
# - "worker": runs LiveKit voice worker
# - "both": runs API server in foreground and worker alongside
COPY <<'EOF' /app/entrypoint.sh
#!/usr/bin/env bash
set -euo pipefail

case "${RUN_MODE:-api}" in
  api)
    echo "Starting FastAPI server on port ${PORT:-8000}..."
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    echo "Starting LiveKit Agent Worker..."
    exec python -m app.worker
    ;;
  both)
    echo "Starting dual API + LiveKit Worker..."
    python -m app.worker &
    WORKER_PID=$!
    uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
    API_PID=$!
    trap 'kill -TERM $WORKER_PID $API_PID' SIGTERM SIGINT
    wait -n
    exit $?
    ;;
  *)
    echo "Unknown RUN_MODE: ${RUN_MODE}. Expected 'api', 'worker', or 'both'." >&2
    exit 1
    ;;
esac
EOF

RUN chmod +x /app/entrypoint.sh

# Create non-root application user (UID 1000 for Hugging Face Spaces compatibility)
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

CMD ["/app/entrypoint.sh"]
