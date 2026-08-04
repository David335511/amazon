"""Monthly search budget enforcement for retailer API lookups.

Design decisions:
- SerpApi free tiers cap the number of searches per calendar month (default
  250). This module tracks usage so lookups are refused once the budget is
  exhausted, and exposes a ``daily_allowance`` so the refresh scheduler can
  pace lookups evenly across the month instead of burning the quota in a day.
- Redis is the source of truth when available (atomic INCR, survives restarts,
  shared across workers). Without Redis it falls back to an in-process counter,
  which is correct for a single worker but not shared between processes.
- Fail-open on Redis errors: if the store is unreachable we allow the request
  rather than break the whole pipeline, but we log it loudly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"retailer:budget:{now:%Y-%m}"


def _first_of_next_month(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=UTC)
    return datetime(now.year, now.month + 1, 1, tzinfo=UTC)


def _seconds_until_next_month(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    return max(1, int((_first_of_next_month(now) - now).total_seconds()))


def _days_left_in_month(now: datetime | None = None) -> int:
    """Number of calendar days remaining this month (today included)."""
    now = now or datetime.now(UTC)
    days = (_first_of_next_month(now).date() - now.date()).days
    return max(1, days)


class RetailerBudget:
    """Tracks and enforces a monthly retailer search budget."""

    def __init__(self, monthly_limit: int, redis_client: Redis | None = None) -> None:
        self._monthly_limit = max(int(monthly_limit), 0)
        self._redis = redis_client
        self._local: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @property
    def monthly_limit(self) -> int:
        """Total searches allowed per calendar month."""
        return self._monthly_limit

    async def used_this_month(self) -> int:
        """Number of searches already spent this calendar month."""
        if self._redis is None:
            async with self._lock:
                return self._local.get(_month_key(), 0)
        try:
            value = await self._redis.get(_month_key())
            return int(value) if value is not None else 0
        except Exception as exc:
            logger.warning("Retailer budget read failed: %s", exc)
            return 0

    async def remaining(self) -> int:
        """Searches still available this month (never negative)."""
        return max(0, self._monthly_limit - await self.used_this_month())

    async def try_acquire(self) -> bool:
        """Atomically reserve one search if the monthly budget allows it.

        Returns True when the token is reserved (caller should release it if the
        request ultimately fails). Returns False when the budget is exhausted.
        """
        if self._redis is None:
            async with self._lock:
                key = _month_key()
                used = self._local.get(key, 0)
                if used >= self._monthly_limit:
                    return False
                self._local[key] = used + 1
                return True
        try:
            key = _month_key()
            used = await self._redis.incr(key)
            if used == 1:
                # First use this month: make sure the key expires with the month.
                await self._redis.expire(key, _seconds_until_next_month())
            if used > self._monthly_limit:
                # Overshot: roll back so the count stays accurate.
                await self._redis.decr(key)
                return False
            return True
        except Exception as exc:
            logger.warning("Retailer budget acquire failed (fail-open): %s", exc)
            return True

    async def release(self) -> None:
        """Return a reserved token when the request did not consume a search."""
        if self._redis is None:
            async with self._lock:
                key = _month_key()
                self._local[key] = max(0, self._local.get(key, 0) - 1)
            return
        try:
            await self._redis.decr(_month_key())
        except Exception as exc:
            logger.warning("Retailer budget release failed: %s", exc)

    async def daily_allowance(self) -> int:
        """Searches we may still spend today without exhausting the month.

        Paces the remaining budget evenly across the days left in the month, so
        a 250/month plan yields ~8/day at the start and grows near month-end if
        quota is left over. Returns 0 when the budget is exhausted.
        """
        remaining = await self.remaining()
        if remaining <= 0:
            return 0
        daily = max(1, remaining // _days_left_in_month())
        return min(daily, remaining)
