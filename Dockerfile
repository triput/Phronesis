# ==============================================================================
# File: Dockerfile
# Description: VN-E02 operator-only image for geek self-host (not the product default)
# Component: Ops / Docker
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
FROM python:3.12-slim-bookworm

WORKDIR /app

# libpq for psycopg2 when DATABASE_URL points at Postgres
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker/entrypoint.sh \
    && mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PHRONESIS_DATA_DIR=/data \
    PORT=8000

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
