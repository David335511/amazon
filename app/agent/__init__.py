"""Autonomous sourcing agent — continuously scans suppliers, evaluates products, and makes decisions.

Architecture:
- Queue: Redis-backed task queue with priority support
- Workers: Concurrent asyncio workers that process tasks
- Pipeline: Full sourcing pipeline (scan → retrieve → calculate → score → recommend → notify)
- Scheduler: Creates supplier cycle tasks on a configurable loop
- Monitor: Real-time observability dashboard
- Logger: Append-only decision log for audit trail
- Notifier: Alerts for high-value opportunities

Design decisions:
- Every component is independent — failures are isolated.
- Workers auto-recover from crashes.
- Queue persists tasks in Redis for durability.
- All decisions are logged immutably.
- The agent can be started, stopped, paused, and resumed via API.
"""

from app.agent.logger import DecisionLogger
from app.agent.models import (
    AgentConfig,
    AgentRunInfo,
    AgentStatus,
    DecisionAction,
    DecisionLog,
    Task,
    TaskStatus,
    TaskType,
    WorkerInfo,
)
from app.agent.monitor import AgentMonitor
from app.agent.notifier import Notifier
from app.agent.pipeline import SourcingPipeline
from app.agent.queue import TaskQueue
from app.agent.scheduler import AgentScheduler
from app.agent.worker import Worker

__all__ = [
    "AgentConfig",
    "AgentRunInfo",
    "AgentStatus",
    "AgentMonitor",
    "AgentScheduler",
    "DecisionAction",
    "DecisionLog",
    "DecisionLogger",
    "Notifier",
    "SourcingPipeline",
    "Task",
    "TaskQueue",
    "TaskStatus",
    "TaskType",
    "Worker",
    "WorkerInfo",
]
