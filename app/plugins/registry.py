"""Plugin registry — discovers and manages supplier plugins.

Design decisions:
- Plugins are discovered by scanning the `app.plugins.suppliers` module
  for classes that subclass `BaseSupplierPlugin`.
- No manual registration needed — add a file to `suppliers/` and it's
  automatically discovered.
- The registry is a singleton for consistent access across the app.
- Plugins can be enabled/disabled per-supplier via configuration.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import httpx

from app.core.logging import get_logger
from app.plugins.base import BaseSupplierPlugin
from app.plugins.config import SupplierConfig, SupplierPluginConfig
from app.plugins.errors import PluginNotFoundError

logger = get_logger(__name__)


class PluginRegistry:
    """Registry that discovers, stores, and provides access to supplier plugins.

    Usage:
        registry = PluginRegistry()
        registry.discover()
        plugin = registry.get("walmart")
        results = await plugin.search("headphones")
    """

    def __init__(self) -> None:
        self._plugins: dict[str, type[BaseSupplierPlugin]] = {}
        self._instances: dict[str, BaseSupplierPlugin] = {}
        self._discovered = False

    def discover(self) -> dict[str, type[BaseSupplierPlugin]]:
        """Discover all supplier plugins by scanning the suppliers package.

        Scans `app.plugins.suppliers` for any class that subclasses
        `BaseSupplierPlugin` and is not the base class itself.

        Returns:
            Dict mapping supplier_code to plugin class.
        """
        if self._discovered:
            return self._plugins

        package = importlib.import_module("app.plugins.suppliers")

        for importer, modname, is_pkg in pkgutil.iter_modules(
            package.__path__,  # type: ignore[arg-type]
            prefix=f"{package.__name__}.",
        ):
            if is_pkg:
                continue

            try:
                module = importlib.import_module(modname)
                self._scan_module(module)
            except Exception as exc:
                logger.warning("Failed to load plugin module %s: %s", modname, exc)

        self._discovered = True
        logger.info(
            "Discovered %d supplier plugins: %s",
            len(self._plugins),
            list(self._plugins.keys()),
        )
        return self._plugins

    def _scan_module(self, module: object) -> None:
        """Scan a module for BaseSupplierPlugin subclasses."""
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseSupplierPlugin)
                and obj is not BaseSupplierPlugin
                and hasattr(obj, "supplier_code")
                and obj.supplier_code
            ):
                self._plugins[obj.supplier_code] = obj
                logger.debug("Discovered plugin: %s (%s)", obj.supplier_name, obj.supplier_code)

    def get_plugin_class(self, supplier_code: str) -> type[BaseSupplierPlugin]:
        """Get a plugin class by supplier code.

        Args:
            supplier_code: Short supplier code (e.g., 'walmart').

        Returns:
            The plugin class.

        Raises:
            PluginNotFoundError: If no plugin matches the code.
        """
        if not self._discovered:
            self.discover()

        plugin_class = self._plugins.get(supplier_code)
        if plugin_class is None:
            raise PluginNotFoundError(supplier_code)
        return plugin_class

    def get(
        self,
        supplier_code: str,
        config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> BaseSupplierPlugin:
        """Get or create a plugin instance by supplier code.

        Instances are cached for the lifetime of the registry.
        To force a fresh instance, use `create()` instead.

        Args:
            supplier_code: Short supplier code.
            config: Supplier-specific configuration.
            http_client: Shared HTTP client.

        Returns:
            An instance of the plugin.
        """
        if supplier_code in self._instances:
            return self._instances[supplier_code]

        instance = self.create(supplier_code, config, http_client)
        self._instances[supplier_code] = instance
        return instance

    def create(
        self,
        supplier_code: str,
        config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> BaseSupplierPlugin:
        """Create a fresh plugin instance (not cached).

        Args:
            supplier_code: Short supplier code.
            config: Supplier-specific configuration.
            http_client: Shared HTTP client.

        Returns:
            A new instance of the plugin.
        """
        plugin_class = self.get_plugin_class(supplier_code)
        return plugin_class(config=config, http_client=http_client)

    def list_plugins(self) -> list[dict[str, str]]:
        """List all discovered plugins with metadata.

        Returns:
            List of dicts with 'code', 'name', 'version'.
        """
        if not self._discovered:
            self.discover()

        return [
            {
                "code": cls.supplier_code,
                "name": cls.supplier_name,
                "version": cls.version,
            }
            for cls in self._plugins.values()
        ]

    def get_enabled_plugins(
        self,
        plugin_config: SupplierPluginConfig | None = None,
    ) -> list[str]:
        """Get codes of all enabled plugins.

        Args:
            plugin_config: Plugin configuration. If None, all discovered
                          plugins are considered enabled.

        Returns:
            List of enabled supplier codes.
        """
        if not self._discovered:
            self.discover()

        if plugin_config is None:
            return list(self._plugins.keys())

        return [
            code
            for code in self._plugins
            if code in plugin_config.suppliers
            and plugin_config.suppliers[code].enabled
        ]

    def clear(self) -> None:
        """Clear all cached instances and force re-discovery."""
        self._plugins.clear()
        self._instances.clear()
        self._discovered = False
