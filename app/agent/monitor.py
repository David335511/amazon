"""Monitoring — real-time agent observability.

Provides metrics, health checks, and status aggregation for the agent system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agent.logger import DecisionLogger
from app.agent.models import AgentRunInfo, AgentStatus
from app.agent.queue import TaskQueue
from app.agent.scheduler import AgentScheduler
from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentMonitor:
    """Monitoring dashboard for the autonomous sourcing agent.

    Aggregates data from the scheduler, queue, workers, and decision log
    into a single status view.
    """

    def __init__(
        self,
        scheduler: AgentScheduler,
        queue: TaskQueue,
        decision_logger: DecisionLogger,
    ) -> None:
        self._scheduler = scheduler
        self._queue = queue
        self._decision_logger = decision_logger

    async def get_dashboard(self) -> dict[str, Any]:
        """Get the complete agent dashboard data."""
        agent_status = self._scheduler.get_status()
        queue_stats = await self._queue.stats()
        decision_stats = await self._decision_logger.stats()

        return {
            "agent": {
                "run_id": agent_status.run_id,
                "status": agent_status.status.value,
                "started_at": agent_status.started_at.isoformat() if agent_status.started_at else None,
                "uptime_seconds": (
                    (datetime.now(timezone.utc) - agent_status.started_at).total_seconds()
                    if agent_status.started_at else 0
                ),
                "cycle_count": agent_status.cycle_count,
                "last_cycle_at": agent_status.last_cycle_at.isoformat() if agent_status.last_cycle_at else None,
            },
            "workers": {
                "total": len(agent_status.workers),
                "active": sum(1 for w in agent_status.workers if w.status == "busy"),
                "idle": sum(1 for w in agent_status.workers if w.status == "idle"),
                "error": sum(1 for w in agent_status.workers if w.status == "error"),
                "details": [
                    {
                        "id": w.worker_id,
                        "status": w.status,
                        "tasks_completed": w.tasks_completed,
                        "tasks_failed": w.tasks_failed,
                        "uptime_seconds": w.uptime_seconds,
                        "current_task": w.current_task_type,
                        "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                    }
                    for w in agent_status.workers
                ],
            },
            "queue": {
                "depth": queue_stats.get("depth", 0),
                "running": queue_stats.get("running", 0),
                "total_enqueued": queue_stats.get("enqueued", 0),
                "total_completed": queue_stats.get("completed", 0),
                "total_failed": queue_stats.get("failed", 0),
            },
            "decisions": {
                "total": decision_stats.get("total_decisions", 0),
                "recent_buy": decision_stats.get("recent_buy", 0),
                "recent_watch": decision_stats.get("recent_watch", 0),
                "recent_avoid": decision_stats.get("recent_avoid", 0),
                "recent_errors": decision_stats.get("recent_errors", 0),
            },
            "errors": agent_status.errors[-10:] if agent_status.errors else [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def health_check(self) -> dict[str, Any]:
        """Get a quick health check."""
        agent_status = self._scheduler.get_status()
        queue_depth = await self._queue.depth()

        is_healthy = (
            agent_status.status in (AgentStatus.RUNNING, AgentStatus.DEGRADED)
        )

        return {
            "healthy": is_healthy,
            "status": agent_status.status.value,
            "workers_active": sum(1 for w in agent_status.workers if w.status != "stopped"),
            "workers_total": len(agent_status.workers),
            "queue_depth": queue_depth,
            "cycle_count": agent_status.cycle_count,
        }
