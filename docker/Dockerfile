# ==============================================================================
# File: docker/Dockerfile
# Description: VN-E02 operator-only image for geek self-host (not the product default)
# Component: Ops / Docker
# Version: 1.1 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-31
# ==============================================================================
# Build from repo root:
#   docker build -f docker/Dockerfile .
# Kept out of the repo root so Railway stays on Railpack/Procfile (geek PaaS path).
FROM python:3.12-slim-bookworm

WORKDIR /app

# libpq for psycopg2 when DATABASE_URL points at Postgres (e.g. Neon)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker/entrypoint.sh \
    && mkdir -p /data

# Do NOT set PHRONESIS_DATA_DIR here: that flag triggers standalone dotenv logic
# which strips orchestrator-injected DATABASE_URL (Railway/Neon, Compose Postgres).
# Compose sets PHRONESIS_DATA_DIR=/data explicitly when a data volume is wanted.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
