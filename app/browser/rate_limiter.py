"""Token-bucket rate limiter for polite crawling.

Allows a configurable number of operations per second while permitting short
bursts. `acquire()` is async so waiting for the next token does not block the
event loop.
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """A thread-safe-async token bucket rate limiter.

    Args:
        rate_per_second: Steady-state operations per second.
        burst: Maximum burst size (tokens).
        delay_min_ms / delay_max_ms: Optional jitter applied on top of the
            bucket, to make request timing look less mechanical.
    """

    def __init__(
        self,
        rate_per_second: float | None = None,
        burst: int | None = None,
        *,
        delay_min_ms: int = 0,
        delay_max_ms: int = 0,
    ) -> None:
        self._rate = rate_per_second if rate_per_second and rate_per_second > 0 else None
        self._burst = burst or (max(1, int(rate_per_second or 1)) if rate_per_second else 1)
        self._tokens = float(self._burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()
        self._delay_min_ms = max(0, delay_min_ms)
        self._delay_max_ms = max(self._delay_min_ms, delay_max_ms)

    async def acquire(self) -> float:
        """Block until a token is available and consume it.

        Returns:
            The delay (in seconds) the caller should additionally sleep to
            apply human-like jitter.
        """
        if self._rate is None:
            return self._random_delay()

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

            if self._tokens < 1.0:
                deficit = 1.0 - self._tokens
                await asyncio.sleep(deficit / self._rate)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0

        return self._random_delay()

    def _random_delay(self) -> float:
        """Return a random jitter delay in seconds within the configured range."""
        if self._delay_max_ms <= 0:
            return 0.0
        import random

        return random.uniform(self._delay_min_ms, self._delay_max_ms) / 1000.0

    async def __aenter__(self) -> RateLimiter:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None
