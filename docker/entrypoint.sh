#!/bin/sh
# ==============================================================================
# File: docker/entrypoint.sh
# Description: VN-E02 container entry — migrate, collectstatic, gunicorn
# Component: Ops / Docker
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-31
# ==============================================================================
set -e
mkdir -p /data /data/logs
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn phronesis_django.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --access-logfile - \
  --error-logfile -
