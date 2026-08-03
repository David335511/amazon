"""Async retry helper with exponential backoff and jitter.

Wraps a coroutine so transient failures (network, timeouts, proxy errors,
soft-blocking) are retried with exponential backoff. Retryable exceptions are
configurable; a non-retryable error propagates immediately.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

RetryPredicate = Callable[[Exception], bool]


def _default_retryable(exc: Exception) -> bool:
    """Default set of retryable exception types."""
    from app.browser.errors import (
        BrowserPoolTimeoutError,
        BrowserRateLimitError,
        BrowserTimeoutError,
        ProxyError,
    )

    return isinstance(
        exc,
        (BrowserTimeoutError, BrowserRateLimitError, ProxyError, BrowserPoolTimeoutError),
    )


async def retry_async[T](
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    backoff_base_ms: int = 1000,
    max_backoff_ms: int = 30000,
    jitter: bool = True,
    retryable: RetryPredicate | None = None,
    **kwargs: Any,
) -> T:
    """Call an async function with exponential backoff retries.

    Args:
        fn: The async callable to invoke.
        max_retries: Max retry attempts after the first call.
        backoff_base_ms: Initial backoff in ms (doubles each retry).
        max_backoff_ms: Cap on the backoff delay.
        jitter: Add random jitter to the backoff to avoid thundering herds.
        retryable: Predicate deciding whether an exception is retryable.

    Returns:
        The result of the first successful call.

    Raises:
        The last exception if all retries are exhausted.
    """
    retryable = retryable or _default_retryable
    attempt = 0
    while True:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            if attempt >= max_retries or not retryable(exc):
                raise
            attempt += 1
            base = backoff_base_ms * (2 ** (attempt - 1))
            delay_ms = min(base, max_backoff_ms)
            if jitter:
                delay_ms = delay_ms * (0.5 + random.random())
            logger.warning(
                "Retry %d/%d after error %s in %dms",
                attempt,
                max_retries,
                exc,
                int(delay_ms),
            )
            await asyncio.sleep(delay_ms / 1000.0)
