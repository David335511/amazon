"""Marketplace registry — discovers and manages marketplace providers.

Design decisions:
- Providers are auto-discovered by scanning the `app.marketplaces.providers`
  package for classes that subclass `MarketplaceProvider`.
- No manual registration needed — add a file to `providers/` and it's
  discovered automatically (this is how future marketplaces are added WITHOUT
  modifying existing code).
- The registry is a singleton for consistent access across the app.
- Providers can be enabled/disabled per-marketplace via configuration.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import httpx

from app.core.logging import get_logger
from app.marketplaces.base import MarketplaceProvider
from app.marketplaces.config import MarketplaceProviderConfig
from app.marketplaces.errors import MarketplaceNotFoundError

logger = get_logger(__name__)


class MarketplaceRegistry:
    """Registry that discovers, stores, and provides access to marketplace providers.

    Usage:
        registry = MarketplaceRegistry()
        registry.discover()
        provider = registry.get("amazon")
        results = await provider.search("headphones")
    """

    def __init__(self) -> None:
        self._providers: dict[str, type[MarketplaceProvider]] = {}
        self._instances: dict[str, MarketplaceProvider] = {}
        self._discovered = False

    def discover(self) -> dict[str, type[MarketplaceProvider]]:
        """Discover all marketplace providers by scanning the providers package.

        Returns:
            Dict mapping marketplace_code to provider class.
        """
        if self._discovered:
            return self._providers

        package = importlib.import_module("app.marketplaces.providers")

        for _importer, modname, is_pkg in pkgutil.iter_modules(
            package.__path__,  # type: ignore[arg-type]
            prefix=f"{package.__name__}.",
        ):
            if is_pkg:
                continue

            try:
                module = importlib.import_module(modname)
                self._scan_module(module)
            except Exception as exc:
                logger.warning("Failed to load marketplace module %s: %s", modname, exc)

        self._discovered = True
        logger.info(
            "Discovered %d marketplace providers: %s",
            len(self._providers),
            list(self._providers.keys()),
        )
        return self._providers

    def _scan_module(self, module: object) -> None:
        """Scan a module for MarketplaceProvider subclasses."""
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, MarketplaceProvider)
                and obj is not MarketplaceProvider
                and hasattr(obj, "marketplace_code")
                and obj.marketplace_code
            ):
                self._providers[obj.marketplace_code] = obj
                logger.debug(
                    "Discovered marketplace: %s (%s)",
                    obj.marketplace_name,
                    obj.marketplace_code,
                )

    def get_provider_class(self, marketplace_code: str) -> type[MarketplaceProvider]:
        """Get a provider class by marketplace code.

        Args:
            marketplace_code: Short marketplace code (e.g. 'amazon').

        Returns:
            The provider class.

        Raises:
            MarketplaceNotFoundError: If no provider matches the code.
        """
        if not self._discovered:
            self.discover()

        provider_class = self._providers.get(marketplace_code)
        if provider_class is None:
            raise MarketplaceNotFoundError(marketplace_code)
        return provider_class

    def get(
        self,
        marketplace_code: str,
        config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> MarketplaceProvider:
        """Get or create a provider instance by marketplace code.

        Instances are cached for the lifetime of the registry.
        To force a fresh instance, use `create()` instead.

        Args:
            marketplace_code: Short marketplace code.
            config: Marketplace-specific configuration.
            http_client: Shared HTTP client.

        Returns:
            An instance of the provider.
        """
        if marketplace_code in self._instances:
            return self._instances[marketplace_code]

        instance = self.create(marketplace_code, config, http_client)
        self._instances[marketplace_code] = instance
        return instance

    def create(
        self,
        marketplace_code: str,
        config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> MarketplaceProvider:
        """Create a fresh provider instance (not cached).

        Args:
            marketplace_code: Short marketplace code.
            config: Marketplace-specific configuration.
            http_client: Shared HTTP client.

        Returns:
            A new instance of the provider.
        """
        provider_class = self.get_provider_class(marketplace_code)
        return provider_class(config=config, http_client=http_client)

    def list_providers(self) -> list[dict[str, str]]:
        """List all discovered providers with metadata.

        Returns:
            List of dicts with 'code', 'name', 'version'.
        """
        if not self._discovered:
            self.discover()

        return [
            {
                "code": cls.marketplace_code,
                "name": cls.marketplace_name,
                "version": cls.version,
            }
            for cls in self._providers.values()
        ]

    def get_enabled_providers(
        self,
        provider_config: MarketplaceProviderConfig | None = None,
    ) -> list[str]:
        """Get codes of all enabled providers.

        Args:
            provider_config: Marketplace configuration. If None, all discovered
                             providers are considered enabled.

        Returns:
            List of enabled marketplace codes.
        """
        if not self._discovered:
            self.discover()

        if provider_config is None:
            return list(self._providers.keys())

        return [
            code
            for code in self._providers
            if code in provider_config.marketplaces
            and provider_config.marketplaces[code].enabled
        ]

    def clear(self) -> None:
        """Clear all cached instances and force re-discovery."""
        self._providers.clear()
        self._instances.clear()
        self._discovered = False
