#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Docker entrypoint — runs Alembic migrations then starts the app
# ──────────────────────────────────────────────────────────────
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn app.main:app \
    --host "${SERVER_HOST:-0.0.0.0}" \
    --port "${SERVER_PORT:-8000}" \
    --workers "${SERVER_WORKERS:-1}" \
    --log-level "${APP_LOG_LEVEL:-info}" \
    --no-access-log \
    --proxy-headers \
    --forwarded-allow-ips '*'
