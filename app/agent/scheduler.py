"""Scheduler — creates tasks on a loop and manages the agent lifecycle.

Design decisions:
- The scheduler creates supplier cycle tasks at configurable intervals.
- It manages worker pool lifecycle (start/stop/restart).
- It tracks agent run state for monitoring.
- Auto-recovery: if a worker dies, it's restarted.
- Graceful shutdown: all workers are stopped before exit.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from app.agent.models import (
    AgentConfig,
    AgentRunInfo,
    AgentStatus,
    Task,
    TaskType,
    WorkerInfo,
)
from app.agent.pipeline import SourcingPipeline
from app.agent.queue import TaskQueue
from app.agent.worker import Worker
from app.core.logging import get_logger
from app.plugins.manager import PluginManager

logger = get_logger(__name__)


class AgentScheduler:
    """Manages the autonomous agent lifecycle.

    Usage:
        scheduler = AgentScheduler(queue, pipeline, plugin_manager, config, redis)
        await scheduler.start()
        # ... agent runs autonomously ...
        await scheduler.stop()
        status = scheduler.get_status()
    """

    def __init__(
        self,
        queue: TaskQueue,
        pipeline: SourcingPipeline,
        plugin_manager: PluginManager,
        config: AgentConfig | None = None,
        redis: Redis | None = None,
    ) -> None:
        self._queue = queue
        self._pipeline = pipeline
        self._plugin_manager = plugin_manager
        self._config = config or AgentConfig()
        self._redis = redis

        self._run_id = str(uuid.uuid4())
        self._run_info = AgentRunInfo(run_id=self._run_id)
        self._workers: list[Worker] = []
        self._scheduler_task: asyncio.Task[Any] | None = None
        self._recovery_task: asyncio.Task[Any] | None = None
        self._running = False

    # ── Lifecycle ───────────────────────────────────────────

    async def start(self) -> None:
        """Start the agent: workers + scheduler loop."""
        if self._running:
            logger.warning("Agent is already running")
            return

        self._running = True
        self._run_info.status = AgentStatus.RUNNING
        self._run_info.started_at = datetime.now(timezone.utc)

        # Start workers
        for i in range(self._config.worker_count):
            worker = Worker(
                worker_id=f"worker-{self._run_id[:8]}-{i}",
                queue=self._queue,
                pipeline=self._pipeline,
                config=self._config,
                redis=self._redis,
            )
            await worker.start()
            self._workers.append(worker)

        # Start scheduler loop
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())

        # Start recovery monitor
        self._recovery_task = asyncio.create_task(self._recovery_loop())

        logger.info(
            "Agent started: run=%s, workers=%d, cycle_interval=%dmin",
            self._run_id[:8],
            self._config.worker_count,
            self._config.cycle_interval_minutes,
        )

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        self._running = False
        self._run_info.status = AgentStatus.STOPPED
        self._run_info.stopped_at = datetime.now(timezone.utc)

        # Stop scheduler
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        # Stop recovery
        if self._recovery_task:
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass

        # Stop workers
        for worker in self._workers:
            await worker.stop()

        logger.info("Agent stopped: run=%s", self._run_id[:8])

    async def pause(self) -> None:
        """Pause the agent (workers finish current tasks, no new cycles)."""
        self._run_info.status = AgentStatus.PAUSED
        logger.info("Agent paused: run=%s", self._run_id[:8])

    async def resume(self) -> None:
        """Resume a paused agent."""
        self._run_info.status = AgentStatus.RUNNING
        logger.info("Agent resumed: run=%s", self._run_id[:8])

    # ── Scheduler Loop ──────────────────────────────────────

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop: create supplier cycles at intervals."""
        # Initial cycle after short delay
        await asyncio.sleep(10)

        while self._running:
            if self._run_info.status == AgentStatus.PAUSED:
                await asyncio.sleep(10)
                continue

            try:
                await self._run_cycle()
            except Exception as exc:
                logger.error("Scheduler cycle failed: %s", exc)
                self._run_info.errors.append(str(exc))
                if len(self._run_info.errors) > 100:
                    self._run_info.errors = self._run_info.errors[-50:]

            # Wait for next cycle
            for _ in range(self._config.cycle_interval_minutes * 60 // 5):
                if not self._running:
                    break
                await asyncio.sleep(5)

    async def _run_cycle(self) -> None:
        """Run one complete sourcing cycle across all suppliers."""
        cycle_start = time.monotonic()
        self._run_info.cycle_count += 1
        cycle_num = self._run_info.cycle_count

        logger.info("Starting cycle %d", cycle_num)

        # Get enabled suppliers
        suppliers = self._plugin_manager.get_enabled_suppliers()
        if not suppliers:
            logger.info("No enabled suppliers found, skipping cycle")
            return

        # Create supplier cycle tasks
        tasks: list[Task] = []
        for supplier_code in suppliers:
            task = Task(
                id=str(uuid.uuid4()),
                type=TaskType.SUPPLIER_CYCLE,
                priority=5,
                payload={
                    "supplier_code": supplier_code,
                },
            )
            tasks.append(task)

        await self._queue.enqueue_many(tasks)
        logger.info(
            "Cycle %d: enqueued %d supplier tasks",
            cycle_num, len(tasks),
        )

        # Wait for tasks to complete (poll queue)
        max_wait = 600  # 10 minutes max
        waited = 0
        while waited < max_wait:
            depth = await self._queue.depth()
            running = await self._queue.running_count()
            if depth == 0 and running == 0:
                break
            await asyncio.sleep(5)
            waited += 5

        # Update run info
        self._run_info.last_cycle_at = datetime.now(timezone.utc)
        stats = await self._queue.stats()
        self._run_info.total_tasks_processed = stats.get("completed", 0) + stats.get("failed", 0)
        self._run_info.total_tasks_succeeded = stats.get("completed", 0)
        self._run_info.total_tasks_failed = stats.get("failed", 0)

        log_stats = await self._pipeline._decision_logger.stats()
        self._run_info.total_decisions_made = log_stats.get("total_decisions", 0)

        duration = time.monotonic() - cycle_start
        logger.info(
            "Cycle %d complete: %.1fs, %d tasks, %d decisions",
            cycle_num, duration,
            self._run_info.total_tasks_processed,
            self._run_info.total_decisions_made,
        )

    # ── Recovery Loop ───────────────────────────────────────

    async def _recovery_loop(self) -> None:
        """Monitor workers and restart any that have failed."""
        while self._running:
            try:
                await asyncio.sleep(30)

                if not self._running:
                    break

                for i, worker in enumerate(self._workers):
                    info = worker.info
                    # Check if worker has stopped unexpectedly
                    if info.status == "stopped" and self._running:
                        logger.warning(
                            "Worker %s stopped unexpectedly, restarting...",
                            worker._worker_id,
                        )
                        new_worker = Worker(
                            worker_id=f"worker-{self._run_id[:8]}-{i}-reborn",
                            queue=self._queue,
                            pipeline=self._pipeline,
                            config=self._config,
                            redis=self._redis,
                        )
                        await new_worker.start()
                        self._workers[i] = new_worker

                # Update agent status
                running_workers = sum(
                    1 for w in self._workers
                    if w.info.status != "stopped"
                )
                if running_workers < len(self._workers):
                    self._run_info.status = AgentStatus.DEGRADED
                elif self._run_info.status == AgentStatus.DEGRADED:
                    self._run_info.status = AgentStatus.RUNNING

                self._run_info.workers = [w.info for w in self._workers]
                self._run_info.queue_depth = await self._queue.depth()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Recovery loop error: %s", exc)
                await asyncio.sleep(10)

    # ── Status ──────────────────────────────────────────────

    def get_status(self) -> AgentRunInfo:
        """Get current agent status."""
        self._run_info.workers = [w.info for w in self._workers]
        return self._run_info

    async def get_worker_status(self) -> list[WorkerInfo]:
        """Get status of all workers."""
        return [w.info for w in self._workers]
