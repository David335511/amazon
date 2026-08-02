"""Redis-backed task queue for the autonomous sourcing agent.

Design decisions:
- Uses Redis lists for FIFO queue semantics.
- Priority is implemented via separate lists per priority level.
- Tasks are serialized as JSON for cross-language compatibility.
- Queue depth and stats are tracked via Redis counters.
- Supports task cancellation and retry with backoff.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from app.agent.models import Task, TaskStatus, TaskType
from app.core.logging import get_logger

logger = get_logger(__name__)

# Redis key prefixes
QUEUE_PREFIX = "agent:queue"
PENDING_SET_KEY = f"{QUEUE_PREFIX}:pending"
RUNNING_SET_KEY = f"{QUEUE_PREFIX}:running"
TASK_KEY_PREFIX = f"{QUEUE_PREFIX}:task"
COUNTER_KEY = f"{QUEUE_PREFIX}:counter"
RETRY_KEY_PREFIX = f"{QUEUE_PREFIX}:retry"


class TaskQueue:
    """Redis-backed task queue with priority support.

    Usage:
        queue = TaskQueue(redis_client)
        await queue.enqueue(Task(type=TaskType.FULL_PIPELINE, payload={...}))
        task = await queue.dequeue()
        await queue.complete(task.id)
    """

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis
        self._local_queue: list[Task] = []  # Fallback when Redis is unavailable

    # ── Enqueue ─────────────────────────────────────────────

    async def enqueue(self, task: Task) -> str:
        """Add a task to the queue.

        Args:
            task: Task to enqueue.

        Returns:
            Task ID.
        """
        if self._redis is not None:
            return await self._enqueue_redis(task)
        return self._enqueue_local(task)

    async def enqueue_many(self, tasks: list[Task]) -> list[str]:
        """Add multiple tasks to the queue efficiently."""
        if self._redis is not None:
            return [await self._enqueue_redis(t) for t in tasks]
        return [self._enqueue_local(t) for t in tasks]

    async def _enqueue_redis(self, task: Task) -> str:
        """Enqueue a task in Redis."""
        task_id = task.id or str(uuid.uuid4())
        task.id = task_id

        # Store task data
        await self._redis.set(
            f"{TASK_KEY_PREFIX}:{task_id}",
            task.model_dump_json(),
            ex=86400,  # 24h TTL
        )

        # Add to priority list (higher priority = lower number = processed first)
        priority_key = f"{QUEUE_PREFIX}:p{task.priority}"
        await self._redis.lpush(priority_key, task_id)

        # Track in pending set
        await self._redis.sadd(PENDING_SET_KEY, task_id)

        # Increment counter
        await self._redis.incr(f"{COUNTER_KEY}:enqueued")

        return task_id

    def _enqueue_local(self, task: Task) -> str:
        """Fallback: enqueue in memory."""
        task_id = task.id or str(uuid.uuid4())
        task.id = task_id
        self._local_queue.append(task)
        return task_id

    # ── Dequeue ─────────────────────────────────────────────

    async def dequeue(
        self,
        worker_id: str,
        timeout: int = 5,
    ) -> Task | None:
        """Dequeue the highest-priority task.

        Args:
            worker_id: ID of the requesting worker.
            timeout: Block timeout in seconds.

        Returns:
            A Task or None if queue is empty.
        """
        if self._redis is not None:
            return await self._dequeue_redis(worker_id, timeout)
        return self._dequeue_local(worker_id)

    async def _dequeue_redis(self, worker_id: str, timeout: int) -> Task | None:
        """Dequeue from Redis using blocking pop across priority levels."""
        # Try priorities 0-10 (lower = higher priority)
        priority_keys = [f"{QUEUE_PREFIX}:p{i}" for i in range(11)]

        # Blocking pop from any priority list
        result = await self._redis.blpop(priority_keys, timeout=timeout)
        if result is None:
            return None

        _, task_id = result
        task_id = task_id.decode() if isinstance(task_id, bytes) else task_id

        # Get task data
        task_data = await self._redis.get(f"{TASK_KEY_PREFIX}:{task_id}")
        if task_data is None:
            return None

        task = Task.model_validate_json(task_data)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        task.worker_id = worker_id

        # Move from pending to running
        await self._redis.srem(PENDING_SET_KEY, task_id)
        await self._redis.sadd(RUNNING_SET_KEY, task_id)

        # Update task in Redis
        await self._redis.set(
            f"{TASK_KEY_PREFIX}:{task_id}",
            task.model_dump_json(),
            ex=86400,
        )

        return task

    def _dequeue_local(self, worker_id: str) -> Task | None:
        """Fallback: dequeue from memory."""
        if not self._local_queue:
            return None
        # Find highest priority
        best_idx = 0
        for i, t in enumerate(self._local_queue):
            if t.priority > self._local_queue[best_idx].priority:
                best_idx = i
        task = self._local_queue.pop(best_idx)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        task.worker_id = worker_id
        return task

    # ── Complete / Fail / Retry ─────────────────────────────

    async def complete(self, task_id: str, result: dict[str, Any] | None = None) -> None:
        """Mark a task as completed successfully."""
        if self._redis is not None:
            await self._complete_redis(task_id, result)
        else:
            self._complete_local(task_id, result)

    async def _complete_redis(self, task_id: str, result: dict[str, Any] | None) -> None:
        task_data = await self._redis.get(f"{TASK_KEY_PREFIX}:{task_id}")
        if task_data is None:
            return
        task = Task.model_validate_json(task_data)
        task.status = TaskStatus.SUCCESS
        task.completed_at = datetime.now(timezone.utc)
        task.result = result
        await self._redis.set(f"{TASK_KEY_PREFIX}:{task_id}", task.model_dump_json(), ex=86400)
        await self._redis.srem(RUNNING_SET_KEY, task_id)
        await self._redis.incr(f"{COUNTER_KEY}:completed")

    def _complete_local(self, task_id: str, result: dict[str, Any] | None) -> None:
        pass  # Local tasks are ephemeral

    async def fail(
        self,
        task_id: str,
        error: str,
        should_retry: bool = True,
    ) -> Task | None:
        """Mark a task as failed, optionally re-enqueuing for retry."""
        if self._redis is not None:
            return await self._fail_redis(task_id, error, should_retry)
        return None

    async def _fail_redis(
        self,
        task_id: str,
        error: str,
        should_retry: bool,
    ) -> Task | None:
        task_data = await self._redis.get(f"{TASK_KEY_PREFIX}:{task_id}")
        if task_data is None:
            return None

        task = Task.model_validate_json(task_data)
        task.retry_count += 1
        task.error = error

        if should_retry and task.retry_count < task.max_retries:
            # Re-enqueue with backoff
            task.status = TaskStatus.RETRYING
            delay = task.retry_count * 10  # 10s, 20s, 30s...
            await self._redis.set(
                f"{RETRY_KEY_PREFIX}:{task_id}",
                task.model_dump_json(),
                ex=delay + 60,
            )
            # Schedule re-enqueue after delay
            await self._redis.setex(
                f"{QUEUE_PREFIX}:scheduled:{task_id}",
                delay,
                task_id,
            )
            logger.info("Task %s will retry in %ds (attempt %d/%d)", task_id, delay, task.retry_count, task.max_retries)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(timezone.utc)
            await self._redis.set(f"{TASK_KEY_PREFIX}:{task_id}", task.model_dump_json(), ex=86400)
            await self._redis.srem(RUNNING_SET_KEY, task_id)
            await self._redis.incr(f"{COUNTER_KEY}:failed")
            logger.error("Task %s failed permanently: %s", task_id, error)

        return task

    # ── Queue Management ────────────────────────────────────

    async def depth(self) -> int:
        """Get the total number of pending tasks."""
        if self._redis is not None:
            return await self._redis.scard(PENDING_SET_KEY)
        return len(self._local_queue)

    async def running_count(self) -> int:
        """Get the number of currently running tasks."""
        if self._redis is not None:
            return await self._redis.scard(RUNNING_SET_KEY)
        return 0

    async def stats(self) -> dict[str, int]:
        """Get queue statistics."""
        if self._redis is not None:
            enqueued = await self._redis.get(f"{COUNTER_KEY}:enqueued") or 0
            completed = await self._redis.get(f"{COUNTER_KEY}:completed") or 0
            failed = await self._redis.get(f"{COUNTER_KEY}:failed") or 0
            return {
                "depth": await self.depth(),
                "running": await self.running_count(),
                "enqueued": int(enqueued),
                "completed": int(completed),
                "failed": int(failed),
            }
        return {
            "depth": len(self._local_queue),
            "running": 0,
            "enqueued": 0,
            "completed": 0,
            "failed": 0,
        }

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending task."""
        if self._redis is not None:
            task_data = await self._redis.get(f"{TASK_KEY_PREFIX}:{task_id}")
            if task_data is None:
                return False
            task = Task.model_validate_json(task_data)
            if task.status != TaskStatus.PENDING:
                return False
            task.status = TaskStatus.CANCELLED
            await self._redis.set(f"{TASK_KEY_PREFIX}:{task_id}", task.model_dump_json(), ex=86400)
            await self._redis.srem(PENDING_SET_KEY, task_id)
            return True
        return False

    async def clear(self) -> int:
        """Clear all pending tasks. Returns count cleared."""
        if self._redis is not None:
            pending = await self._redis.smembers(PENDING_SET_KEY)
            if pending:
                await self._redis.delete(*[f"{TASK_KEY_PREFIX}:{t}" for t in pending])
                await self._redis.delete(PENDING_SET_KEY)
                for i in range(11):
                    await self._redis.delete(f"{QUEUE_PREFIX}:p{i}")
            return len(pending)
        count = len(self._local_queue)
        self._local_queue.clear()
        return count
