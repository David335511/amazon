"""Supplier plugin implementations.

Each module in this package implements one supplier plugin.
Plugins are auto-discovered by PluginRegistry — no manual registration needed.
"""

from app.plugins.suppliers.walmart import WalmartPlugin
from app.plugins.suppliers.target import TargetPlugin
from app.plugins.suppliers.homedepot import HomeDepotPlugin
from app.plugins.suppliers.costco import CostcoPlugin
from app.plugins.suppliers.bestbuy import BestBuyPlugin

__all__ = [
    "WalmartPlugin",
    "TargetPlugin",
    "HomeDepotPlugin",
    "CostcoPlugin",
    "BestBuyPlugin",
]
