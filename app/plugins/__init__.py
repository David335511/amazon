"""Supplier plugin system for the Amazon sourcing platform.

Provides a pluggable architecture for integrating unlimited suppliers.
Each supplier implements the `BaseSupplierPlugin` interface with 8
required methods. Plugins are auto-discovered by the `PluginRegistry`
and managed by the `PluginManager`.
"""

from app.plugins.base import BaseSupplierPlugin
from app.plugins.config import SupplierConfig, SupplierPluginConfig
from app.plugins.errors import (
    PluginAuthenticationError,
    PluginError,
    PluginMethodNotImplementedError,
    PluginNotFoundError,
    PluginParseError,
    PluginRateLimitError,
    PluginRequestError,
)
from app.plugins.manager import PluginManager
from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierInventory,
    SupplierPricing,
    SupplierProductLookup,
    SupplierProductSearchResult,
    SupplierShipping,
)
from app.plugins.registry import PluginRegistry

__all__ = [
    "BaseSupplierPlugin",
    "SupplierConfig",
    "SupplierPluginConfig",
    "PluginError",
    "PluginNotFoundError",
    "PluginMethodNotImplementedError",
    "PluginAuthenticationError",
    "PluginRateLimitError",
    "PluginRequestError",
    "PluginParseError",
    "PluginManager",
    "PluginRegistry",
    "SupplierProductSearchResult",
    "SupplierProductLookup",
    "SupplierPricing",
    "SupplierInventory",
    "SupplierShipping",
    "SupplierCoupon",
    "SupplierAvailability",
]
