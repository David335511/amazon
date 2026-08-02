"""Decision logger — append-only log of all agent decisions.

Design decisions:
- Every decision is logged as an immutable record.
- Logs are stored in Redis for fast access and in a local buffer for fallback.
- Logs include full context: product data, scores, reasoning, and errors.
- Retention is configurable via AgentConfig.log_retention_days.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from app.agent.models import DecisionAction, DecisionLog
from app.core.logging import get_logger

logger = get_logger(__name__)

LOG_KEY_PREFIX = "agent:decisions"
LOG_INDEX_KEY = f"{LOG_KEY_PREFIX}:index"
LOG_COUNTER_KEY = f"{LOG_KEY_PREFIX}:counter"


class DecisionLogger:
    """Append-only logger for sourcing decisions.

    Usage:
        logger = DecisionLogger(redis_client)
        await logger.log(decision)
        recent = await logger.get_recent(limit=20)
    """

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis
        self._buffer: list[DecisionLog] = []

    async def log(self, decision: DecisionLog) -> str:
        """Record a decision.

        Args:
            decision: The decision to log.

        Returns:
            Decision ID.
        """
        decision.id = decision.id or str(uuid.uuid4())

        if self._redis is not None:
            await self._redis.set(
                f"{LOG_KEY_PREFIX}:{decision.id}",
                decision.model_dump_json(),
                ex=86400 * 90,  # 90 day retention
            )
            await self._redis.lpush(LOG_INDEX_KEY, decision.id)
            await self._redis.ltrim(LOG_INDEX_KEY, 0, 9999)  # Keep last 10k IDs
            await self._redis.incr(LOG_COUNTER_KEY)

        self._buffer.append(decision)
        if len(self._buffer) > 1000:
            self._buffer = self._buffer[-500:]

        return decision.id

    async def get_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        action: DecisionAction | None = None,
    ) -> list[DecisionLog]:
        """Get recent decisions with optional filtering."""
        if self._redis is not None:
            return await self._get_recent_redis(limit, offset, action)

        # Fallback: return from buffer
        results = list(reversed(self._buffer))
        if action:
            results = [d for d in results if d.action == action]
        return results[offset:offset + limit]

    async def _get_recent_redis(
        self,
        limit: int,
        offset: int,
        action: DecisionAction | None,
    ) -> list[DecisionLog]:
        ids = await self._redis.lrange(LOG_INDEX_KEY, offset, offset + limit - 1)
        if not ids:
            return []

        decisions: list[DecisionLog] = []
        for log_id in ids:
            data = await self._redis.get(f"{LOG_KEY_PREFIX}:{log_id}")
            if data:
                try:
                    decision = DecisionLog.model_validate_json(data)
                    if action is None or decision.action == action:
                        decisions.append(decision)
                except Exception:
                    continue

        return decisions

    async def count(self) -> int:
        """Get total number of decisions logged."""
        if self._redis is not None:
            val = await self._redis.get(LOG_COUNTER_KEY)
            return int(val) if val else 0
        return len(self._buffer)

    async def get_by_id(self, decision_id: str) -> DecisionLog | None:
        """Get a specific decision by ID."""
        if self._redis is not None:
            data = await self._redis.get(f"{LOG_KEY_PREFIX}:{decision_id}")
            if data:
                return DecisionLog.model_validate_json(data)
        return None

    async def stats(self) -> dict[str, Any]:
        """Get decision statistics."""
        total = await self.count()
        recent = await self.get_recent(limit=100)
        buy_count = sum(1 for d in recent if d.action == DecisionAction.BUY)
        watch_count = sum(1 for d in recent if d.action == DecisionAction.WATCH)
        avoid_count = sum(1 for d in recent if d.action == DecisionAction.AVOID)
        error_count = sum(1 for d in recent if d.action == DecisionAction.ERROR)

        return {
            "total_decisions": total,
            "recent_buy": buy_count,
            "recent_watch": watch_count,
            "recent_avoid": avoid_count,
            "recent_errors": error_count,
            "recent_total": len(recent),
        }
