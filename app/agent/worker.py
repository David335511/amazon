"""Worker — processes tasks from the queue with auto-recovery.

Design decisions:
- Each worker runs in an asyncio task with its own event loop.
- Workers heartbeat to Redis for monitoring.
- Tasks have configurable timeouts — killed if exceeded.
- Workers auto-recover from failures by re-enqueuing tasks.
- Graceful shutdown via cancellation token.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agent.models import (
    AgentConfig,
    Task,
    TaskStatus,
    TaskType,
    WorkerInfo,
)
from app.agent.pipeline import SourcingPipeline
from app.agent.queue import TaskQueue
from app.core.logging import get_logger
from redis.asyncio import Redis

logger = get_logger(__name__)


class Worker:
    """A single worker that processes tasks from the queue.

    Usage:
        worker = Worker(worker_id, queue, pipeline, config, redis)
        await worker.start()
        # ... later ...
        await worker.stop()
    """

    def __init__(
        self,
        worker_id: str,
        queue: TaskQueue,
        pipeline: SourcingPipeline,
        config: AgentConfig,
        redis: Redis | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._queue = queue
        self._pipeline = pipeline
        self._config = config
        self._redis = redis
        self._task: asyncio.Task[Any] | None = None
        self._running = False
        self._info = WorkerInfo(worker_id=worker_id)
        self._heartbeat_task: asyncio.Task[Any] | None = None

    @property
    def info(self) -> WorkerInfo:
        """Get current worker info."""
        self._info.uptime_seconds = (
            datetime.now(timezone.utc) - self._info.started_at
        ).total_seconds()
        return self._info

    async def start(self) -> None:
        """Start the worker loop."""
        if self._running:
            return
        self._running = True
        self._info.started_at = datetime.now(timezone.utc)
        self._info.status = "idle"

        self._task = asyncio.create_task(self._run_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("Worker %s started", self._worker_id)

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._info.status = "stopped"
        logger.info("Worker %s stopped", self._worker_id)

    async def _run_loop(self) -> None:
        """Main worker loop: dequeue → process → complete."""
        while self._running:
            try:
                task = await self._queue.dequeue(
                    self._worker_id,
                    timeout=5,
                )
                if task is None:
                    await asyncio.sleep(0.5)
                    continue

                self._info.status = "busy"
                self._info.current_task_id = task.id
                self._info.current_task_type = task.type.value

                await self._process_task(task)

                self._info.status = "idle"
                self._info.current_task_id = None
                self._info.current_task_type = None

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Worker %s loop error: %s",
                    self._worker_id, exc,
                )
                self._info.status = "error"
                await asyncio.sleep(2)

    async def _process_task(self, task: Task) -> None:
        """Process a single task with timeout protection."""
        try:
            async with asyncio.timeout(self._config.task_timeout_seconds):
                result = await self._execute_task(task)
                await self._queue.complete(task.id, result)
                self._info.tasks_completed += 1
        except asyncio.TimeoutError:
            logger.warning(
                "Task %s timed out after %ds",
                task.id, self._config.task_timeout_seconds,
            )
            await self._queue.fail(task.id, "Task timed out", should_retry=True)
            self._info.tasks_failed += 1
        except Exception as exc:
            logger.error("Task %s failed: %s", task.id, exc)
            await self._queue.fail(task.id, str(exc), should_retry=True)
            self._info.tasks_failed += 1

    async def _execute_task(self, task: Task) -> dict[str, Any]:
        """Execute a task based on its type."""
        payload = task.payload

        if task.type == TaskType.SCAN_SUPPLIER:
            products = await self._pipeline.scan_supplier(
                supplier_code=payload.get("supplier_code", ""),
                page=payload.get("page", 1),
                page_size=payload.get("page_size", 20),
            )
            return {"products": products, "count": len(products)}

        if task.type == TaskType.RETRIEVE_AMAZON:
            data = await self._pipeline.retrieve_amazon_data(
                asin=payload.get("asin", ""),
            )
            return {"amazon_data": data}

        if task.type == TaskType.FULL_PIPELINE:
            decision = await self._pipeline.run_full_pipeline(
                supplier_code=payload.get("supplier_code", ""),
                supplier_sku=payload.get("supplier_sku", ""),
                product_title=payload.get("title", ""),
                supplier_price=float(payload.get("price", 0)),
                asin=payload.get("asin"),
                upc=payload.get("upc"),
            )
            return {
                "decision_id": decision.id,
                "action": decision.action.value,
                "score": decision.opportunity_score,
            }

        if task.type == TaskType.SUPPLIER_CYCLE:
            return await self._run_supplier_cycle(task)

        return {"status": "unknown_task_type"}

    async def _run_supplier_cycle(self, task: Task) -> dict[str, Any]:
        """Run a complete supplier cycle: scan → pipeline for each product."""
        supplier_code = task.payload.get("supplier_code", "")
        page_size = self._config.scan_page_size
        max_products = self._config.max_products_per_supplier_per_cycle

        products_processed = 0
        decisions_made = 0
        page = 1

        while products_processed < max_products:
            products = await self._pipeline.scan_supplier(
                supplier_code, page=page, page_size=page_size,
            )
            if not products:
                break

            for product in products:
                if products_processed >= max_products:
                    break

                decision = await self._pipeline.run_full_pipeline(
                    supplier_code=supplier_code,
                    supplier_sku=product.get("supplier_sku", ""),
                    product_title=product.get("title", ""),
                    supplier_price=float(product.get("price", 0)),
                    asin=None,  # Will be matched by UPC
                    upc=product.get("upc"),
                )
                decisions_made += 1
                products_processed += 1

            page += 1

        return {
            "supplier_code": supplier_code,
            "products_scanned": products_processed,
            "decisions_made": decisions_made,
        }

    async def _heartbeat_loop(self) -> None:
        """Periodically update worker heartbeat in Redis."""
        while self._running:
            try:
                self._info.last_heartbeat = datetime.now(timezone.utc)
                self._info.uptime_seconds = (
                    datetime.now(timezone.utc) - self._info.started_at
                ).total_seconds()

                if self._redis is not None:
                    await self._redis.set(
                        f"agent:worker:{self._worker_id}",
                        self.info.model_dump_json(),
                        ex=120,  # 2 minute TTL
                    )

                await asyncio.sleep(self._config.heartbeat_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Heartbeat error for worker %s: %s", self._worker_id, exc)
                await asyncio.sleep(10)
