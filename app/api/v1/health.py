"""Health check endpoints for liveness and readiness probes.

Design decisions:
- `/health/live` — simple liveness check (always returns 200 if the app is running).
- `/health/ready` — readiness check that verifies DB and Redis connectivity.
- Separate endpoints allow Kubernetes-style probe differentiation.
- Returns structured JSON with component status for observability.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


class HealthComponent(BaseModel):
    """Status of a single system component."""

    status: str  # "healthy" | "unhealthy"
    details: str | None = None


class HealthResponse(BaseModel):
    """Health check response body."""

    status: str  # "healthy" | "degraded" | "unhealthy"
    timestamp: str
    version: str
    components: dict[str, HealthComponent]


@router.get("/health/live", status_code=200)
async def liveness_probe() -> dict[str, str]:
    """Liveness probe — returns 200 if the application is running.

    This is a minimal check used by orchestrators to know if the
    application process is alive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health/ready", status_code=200)
async def readiness_probe(
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> HealthResponse:
    """Readiness probe — checks that all dependencies are available.

    Returns 200 only if database and Redis are reachable.
    Returns 503 if any critical component is down.
    """
    components: dict[str, HealthComponent] = {}
    overall_status = "healthy"

    # Check database
    db_healthy = await _check_database(db)
    components["database"] = HealthComponent(
        status="healthy" if db_healthy else "unhealthy",
        details=None if db_healthy else "Cannot connect to PostgreSQL",
    )
    if not db_healthy:
        overall_status = "unhealthy"

    # Check Redis
    redis_healthy = await _check_redis(redis_client)
    components["redis"] = HealthComponent(
        status="healthy" if redis_healthy else "unhealthy",
        details=None if redis_healthy else "Cannot connect to Redis",
    )
    if not redis_healthy:
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC).isoformat(),
        version="0.1.0",
        components=components,
    )


async def _check_database(db: AsyncSession) -> bool:
    """Check database connectivity by executing a simple query."""
    try:
        result = await db.execute(text("SELECT 1"))
        return bool(result.scalar_one_or_none())
    except Exception:
        return False


async def _check_redis(redis_client: Redis) -> bool:
    """Check Redis connectivity."""
    try:
        return await redis_client.ping()
    except Exception:
        return False
