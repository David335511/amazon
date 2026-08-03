"""Agent API routes — manage the autonomous sourcing agent.

Endpoints:
- POST /agent/start — Start the agent
- POST /agent/stop — Stop the agent
- POST /agent/pause — Pause the agent
- POST /agent/resume — Resume the agent
- GET /agent/status — Get agent status
- GET /agent/dashboard — Get full monitoring dashboard
- GET /agent/health — Health check
- GET /agent/decisions — Get recent decisions
- GET /agent/decisions/{id} — Get a specific decision
- POST /agent/queue/clear — Clear the task queue
- GET /agent/config — Get agent configuration
- PUT /agent/config — Update agent configuration
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import (
    AgentConfig,
    AgentMonitor,
    AgentScheduler,
    DecisionLogger,
    Notifier,
    SourcingPipeline,
    TaskQueue,
)
from app.agent.models import DecisionAction, DecisionLog
from app.analytics.repository import AnalyticsRepository
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.dependencies import get_memory_manager
from app.memory import MemoryManager
from app.plugins.manager import PluginManager
from app.plugins.registry import PluginRegistry
from app.plugins.config import SupplierPluginConfig
from app.sourcing.engine import SourcingEngine
from redis.asyncio import Redis

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# Global agent instance
_agent_scheduler: AgentScheduler | None = None
_agent_config: AgentConfig = AgentConfig()


# ── Dependency ──────────────────────────────────────────────


async def get_agent_deps(
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    memory_manager: MemoryManager = Depends(get_memory_manager),
) -> dict[str, Any]:
    """Create or return the global agent instance."""
    global _agent_scheduler

    if _agent_scheduler is not None:
        return {"scheduler": _agent_scheduler, "config": _agent_config}

    # First-time initialization
    analytics_repo = AnalyticsRepository(db)
    sourcing_engine = SourcingEngine(repository=analytics_repo)
    task_queue = TaskQueue(redis_client)
    decision_logger = DecisionLogger(redis_client)
    notifier = Notifier(min_score_to_notify=_agent_config.min_opportunity_score_to_notify)

    # Plugin manager
    registry = PluginRegistry()
    registry.discover()
    plugin_config = SupplierPluginConfig()
    plugin_manager = PluginManager(registry=registry, config=plugin_config)
    await plugin_manager.initialize()

    pipeline = SourcingPipeline(
        plugin_manager=plugin_manager,
        sourcing_engine=sourcing_engine,
        analytics_repo=analytics_repo,
        decision_logger=decision_logger,
        notifier=notifier,
        agent_run_id="api-triggered",
        memory_manager=memory_manager,
    )

    scheduler = AgentScheduler(
        queue=task_queue,
        pipeline=pipeline,
        plugin_manager=plugin_manager,
        config=_agent_config,
        redis=redis_client,
    )

    _agent_scheduler = scheduler
    return {"scheduler": scheduler, "config": _agent_config}


# ═══════════════════════════════════════════════════════════════
# Agent Lifecycle
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/start",
    summary="Start the autonomous agent",
    description="Starts the agent with the configured number of workers and begins the sourcing cycle.",
)
async def start_agent(
    deps: dict[str, Any] = Depends(get_agent_deps),
) -> dict[str, str]:
    """Start the autonomous sourcing agent."""
    scheduler = deps["scheduler"]
    await scheduler.start()
    return {"status": "started", "run_id": scheduler._run_id}


@router.post(
    "/stop",
    summary="Stop the autonomous agent",
    description="Gracefully stops the agent and all workers.",
)
async def stop_agent(
    deps: dict[str, Any] = Depends(get_agent_deps),
) -> dict[str, str]:
    """Stop the autonomous sourcing agent."""
    scheduler = deps["scheduler"]
    await scheduler.stop()
    return {"status": "stopped"}


@router.post(
    "/pause",
    summary="Pause the agent",
    description="Pauses the agent. Workers finish current tasks but no new cycles start.",
)
async def pause_agent(
    deps: dict[str, Any] = Depends(get_agent_deps),
) -> dict[str, str]:
    """Pause the autonomous sourcing agent."""
    scheduler = deps["scheduler"]
    await scheduler.pause()
    return {"status": "paused"}


@router.post(
    "/resume",
    summary="Resume the agent",
    description="Resumes a paused agent.",
)
async def resume_agent(
    deps: dict[str, Any] = Depends(get_agent_deps),
) -> dict[str, str]:
    """Resume the autonomous sourcing agent."""
    scheduler = deps["scheduler"]
    await scheduler.resume()
    return {"status": "resumed"}


# ═══════════════════════════════════════════════════════════════
# Status & Monitoring
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/status",
    summary="Get agent status",
    description="Returns the current status of the agent, workers, queue, and decisions.",
)
async def get_agent_status(
    deps: dict[str, Any] = Depends(get_agent_deps),
) -> dict[str, Any]:
    """Get the current agent status."""
    scheduler = deps["scheduler"]
    return scheduler.get_status().model_dump()


@router.get(
    "/dashboard",
    summary="Get agent dashboard",
    description="Returns the full monitoring dashboard with all metrics.",
)
async def get_agent_dashboard(
    deps: dict[str, Any] = Depends(get_agent_deps),
    redis_client: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Get the full agent monitoring dashboard."""
    scheduler = deps["scheduler"]
    queue = scheduler._queue
    # Get decision logger from pipeline
    decision_logger = scheduler._pipeline._decision_logger
    monitor = AgentMonitor(scheduler, queue, decision_logger)
    return await monitor.get_dashboard()


@router.get(
    "/health",
    summary="Agent health check",
    description="Quick health check for the agent system.",
)
async def agent_health(
    deps: dict[str, Any] = Depends(get_agent_deps),
    redis_client: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Health check for the agent."""
    scheduler = deps["scheduler"]
    queue = scheduler._queue
    decision_logger = scheduler._pipeline._decision_logger
    monitor = AgentMonitor(scheduler, queue, decision_logger)
    return await monitor.health_check()


# ═══════════════════════════════════════════════════════════════
# Decisions
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/decisions",
    summary="Get recent decisions",
    description="Returns recent sourcing decisions made by the agent.",
)
async def get_recent_decisions(
    limit: int = Query(default=50, ge=1, le=200, description="Number of decisions"),
    action: str | None = Query(default=None, description="Filter by action: BUY, WATCH, AVOID"),
    deps: dict[str, Any] = Depends(get_agent_deps),
    redis_client: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Get recent sourcing decisions."""
    decision_logger = DecisionLogger(redis_client)
    action_filter = DecisionAction(action.upper()) if action else None
    decisions = await decision_logger.get_recent(
        limit=limit,
        action=action_filter,
    )
    return {
        "decisions": [d.model_dump() for d in decisions],
        "total": len(decisions),
    }


@router.get(
    "/decisions/{decision_id}",
    summary="Get a specific decision",
    description="Returns a specific sourcing decision by ID.",
)
async def get_decision(
    decision_id: str,
    redis_client: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Get a specific decision by ID."""
    decision_logger = DecisionLogger(redis_client)
    decision = await decision_logger.get_by_id(decision_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision '{decision_id}' not found",
        )
    return decision.model_dump()


# ═══════════════════════════════════════════════════════════════
# Queue Management
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/queue/clear",
    summary="Clear the task queue",
    description="Removes all pending tasks from the queue.",
)
async def clear_queue(
    deps: dict[str, Any] = Depends(get_agent_deps),
) -> dict[str, Any]:
    """Clear all pending tasks."""
    scheduler = deps["scheduler"]
    count = await scheduler._queue.clear()
    return {"cleared": count, "status": "ok"}


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/config",
    summary="Get agent configuration",
    description="Returns the current agent configuration.",
)
async def get_agent_config() -> AgentConfig:
    """Get the current agent configuration."""
    return _agent_config


@router.put(
    "/config",
    summary="Update agent configuration",
    description="Updates the agent configuration. Some changes may require a restart.",
)
async def update_agent_config(
    config: AgentConfig,
) -> dict[str, Any]:
    """Update the agent configuration."""
    global _agent_config
    _agent_config = config
    return {"status": "updated", "config": config.model_dump()}
