#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Docker entrypoint — runs Alembic migrations then starts the app
# ──────────────────────────────────────────────────────────────
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
# uvicorn requires lowercase log levels; APP_LOG_LEVEL may be uppercase (e.g. INFO)
LOG_LEVEL="${APP_LOG_LEVEL:-info}"
exec uvicorn app.main:app \
    --host "${SERVER_HOST:-0.0.0.0}" \
    --port "${SERVER_PORT:-8000}" \
    --workers "${SERVER_WORKERS:-1}" \
    --log-level "${LOG_LEVEL,,}" \
    --no-access-log \
    --proxy-headers \
    --forwarded-allow-ips '*'
