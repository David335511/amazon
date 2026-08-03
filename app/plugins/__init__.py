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
    "PluginAuthenticationError",
    "PluginError",
    "PluginManager",
    "PluginMethodNotImplementedError",
    "PluginNotFoundError",
    "PluginParseError",
    "PluginRateLimitError",
    "PluginRegistry",
    "PluginRequestError",
    "SupplierAvailability",
    "SupplierConfig",
    "SupplierCoupon",
    "SupplierInventory",
    "SupplierPluginConfig",
    "SupplierPricing",
    "SupplierProductLookup",
    "SupplierProductSearchResult",
    "SupplierShipping",
]
