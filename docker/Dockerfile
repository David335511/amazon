# ──────────────────────────────────────────────────────────────
# Dockerfile — Multi-stage build for Amazon AI Commerce Platform
# ──────────────────────────────────────────────────────────────

# ── Stage 1: Base ───────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 2: Dependencies ────────────────────────────────────
FROM base AS dependencies

COPY pyproject.toml ./

# Install uv
RUN pip install uv

# Install project dependencies
RUN uv pip install --system --no-cache \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "sqlalchemy>=2.0.35" \
    "asyncpg>=0.30.0" \
    "alembic>=1.13.0" \
    "redis[hiredis]>=5.1.0" \
    "pydantic>=2.9.0" \
    "pydantic-settings>=2.5.0" \
    "pyyaml>=6.0.2" \
    "structlog>=24.4.0" \
    "opentelemetry-api>=1.27.0" \
    "opentelemetry-sdk>=1.27.0" \
    "opentelemetry-instrumentation-fastapi>=0.48b0" \
    "opentelemetry-instrumentation-sqlalchemy>=0.48b0" \
    "opentelemetry-instrumentation-redis>=0.48b0" \
    "httptools>=0.6.1" \
    "python-multipart>=0.0.12"

# ── Stage 3: Runtime ────────────────────────────────────────
FROM base AS runtime

COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create non-root user
RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --gid 1001 app && \
    chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live')" || exit 1

ENTRYPOINT ["/bin/bash", "/app/docker/entrypoint.sh"]
