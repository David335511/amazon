"""Proxy pool management with rotation and ban tracking.

Holds a pool of proxies, assigns one per browser context according to a
rotation policy, tracks failure counts, and automatically suspends proxies that
exceed a failure threshold. Exposes the assigned proxy in Playwright's
`proxy` dict format expected by `browser.new_context(proxy=...)`.
"""

from __future__ import annotations

import itertools
import logging
import random
from collections import Counter
from typing import Any

from app.browser.config import BrowserProxyConfig, ProxyConfig
from app.browser.errors import ProxyExhaustedError

logger = logging.getLogger(__name__)


class ProxyManager:
    """Manages a pool of proxies.

    Args:
        config: Proxy configuration (or a plain dict).
    """

    def __init__(self, config: BrowserProxyConfig | dict[str, Any] | None = None) -> None:
        if config is None:
            self._config = BrowserProxyConfig()
        elif isinstance(config, BrowserProxyConfig):
            self._config = config
        else:
            self._config = BrowserProxyConfig.model_validate(config)

        self._proxies: list[ProxyConfig] = [
            p for p in self._config.proxies if p.enabled
        ]
        self._failures: Counter[str] = Counter()
        self._banned: set[str] = set()
        self._rr = itertools.cycle(range(len(self._proxies))) if self._proxies else itertools.cycle(())

    @property
    def enabled_count(self) -> int:
        """Number of proxies currently available (not banned)."""
        return len(self._proxies) - len(self._banned)

    @property
    def has_proxies(self) -> bool:
        """Whether any proxy is available."""
        return self.enabled_count > 0

    def get_proxy(self, sticky_key: str | None = None) -> dict[str, Any] | None:
        """Return the next proxy in Playwright's proxy-dict format.

        Args:
            sticky_key: Optional key to pin a proxy to a caller (sticky rotation).

        Returns:
            A dict like ``{"server": ..., "username": ..., "password": ...}``,
            or ``None`` if no proxies are configured.
        """
        if not self._proxies:
            return None

        available = [i for i, p in enumerate(self._proxies) if self.url(p) not in self._banned]
        if not available:
            raise ProxyExhaustedError("All configured proxies are banned or failed health checks.")

        if sticky_key is not None:
            return self._sticky(available, sticky_key)

        if self._config.rotation == "random":
            index = random.choice(available)
        elif self._config.rotation == "sticky":
            index = available[0]
        else:  # round_robin
            # Advance the shared round-robin until we land on an available one.
            while True:
                index = next(self._rr)
                if index in available:
                    break

        proxy = self._proxies[index]
        return self._to_playwright(proxy)

    def _sticky(self, available: list[int], key: str) -> dict[str, Any]:
        """Deterministically pick a proxy for a sticky key."""
        index = available[hash(key) % len(available)]
        return self._to_playwright(self._proxies[index])

    def mark_failure(self, proxy: dict[str, Any] | None) -> None:
        """Record a failure for the given proxy and ban it if threshold is hit.

        Args:
            proxy: The proxy dict previously returned by `get_proxy`.
        """
        if not proxy:
            return
        url = self._dict_url(proxy)
        self._failures[url] += 1
        if self._failures[url] >= self._config.max_failures_before_ban:
            self._banned.add(url)
            logger.warning("Proxy banned after %d failures: %s", self._failures[url], url)

    def mark_success(self, proxy: dict[str, Any] | None) -> None:
        """Reset failure state for a proxy after a successful request."""
        if not proxy:
            return
        url = self._dict_url(proxy)
        if url in self._failures:
            del self._failures[url]
        if url in self._banned:
            self._banned.discard(url)

    def list_proxies(self) -> list[dict[str, Any]]:
        """Return metadata about all configured proxies."""
        return [
            {
                "url": self.url(p),
                "weight": p.weight,
                "enabled": p.enabled,
                "failures": self._failures[self.url(p)],
                "banned": self.url(p) in self._banned,
            }
            for p in self._proxies
        ]

    def reset(self) -> None:
        """Clear all ban and failure state."""
        self._failures.clear()
        self._banned.clear()

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def url(proxy: ProxyConfig) -> str:
        """Normalized URL string for a proxy."""
        return proxy.url.rstrip("/")

    @staticmethod
    def _to_playwright(proxy: ProxyConfig) -> dict[str, Any]:
        result: dict[str, Any] = {"server": proxy.url}
        if proxy.username:
            result["username"] = proxy.username
        if proxy.password:
            result["password"] = proxy.password
        return result

    @staticmethod
    def _dict_url(proxy: dict[str, Any]) -> str:
        return proxy.get("server", "").rstrip("/")
