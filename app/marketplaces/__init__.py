"""Marketplace abstraction layer.

A pluggable layer that lets the platform interact with ANY selling marketplace
(Amazon, eBay, Walmart, TikTok Shop, Facebook Marketplace, Etsy, ...) through a
single `MarketplaceProvider` interface. No marketplace-specific logic exists
outside this package's provider implementations.

Design decisions:
- `MarketplaceProvider` is the only contract the rest of the platform may
  depend on. It exposes 12 uniform capabilities: search, lookup, pricing, fees,
  inventory, orders, listings, competition, sales_estimate, buybox, shipping,
  returns.
- Providers are auto-discovered by `MarketplaceRegistry` — adding a new
  marketplace is a matter of dropping in a `MarketplaceProvider` subclass with
  NO changes to existing code.
- `MarketplaceManager` is the single entry point for the rest of the platform
  and provides error isolation across marketplaces.
- Capabilities a marketplace cannot provide degrade gracefully (``supported=False``)
  rather than raising.
"""

from app.marketplaces.base import CAPABILITIES, MarketplaceProvider
from app.marketplaces.config import MarketplaceConfig, MarketplaceProviderConfig
from app.marketplaces.errors import (
    MarketplaceAuthenticationError,
    MarketplaceConfigurationError,
    MarketplaceError,
    MarketplaceMethodNotImplementedError,
    MarketplaceNotEnabledError,
    MarketplaceNotFoundError,
    MarketplaceParseError,
    MarketplaceRateLimitError,
    MarketplaceRequestError,
)
from app.marketplaces.manager import MarketplaceManager
from app.marketplaces.models import (
    MarketplaceBuyBox,
    MarketplaceCompetition,
    MarketplaceFees,
    MarketplaceInventory,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplacePricing,
    MarketplaceProduct,
    MarketplaceResult,
    MarketplaceReturn,
    MarketplaceSalesEstimate,
    MarketplaceSearchResult,
    MarketplaceShipping,
    MarketplaceShippingOption,
)
from app.marketplaces.registry import MarketplaceRegistry

__all__ = [
    "CAPABILITIES",
    "MarketplaceAuthenticationError",
    "MarketplaceBuyBox",
    "MarketplaceCompetition",
    "MarketplaceConfig",
    "MarketplaceConfigurationError",
    "MarketplaceError",
    "MarketplaceFees",
    "MarketplaceInventory",
    "MarketplaceListing",
    "MarketplaceManager",
    "MarketplaceMethodNotImplementedError",
    "MarketplaceNotEnabledError",
    "MarketplaceNotFoundError",
    "MarketplaceOrder",
    "MarketplaceOrderItem",
    "MarketplaceParseError",
    "MarketplacePricing",
    "MarketplaceProduct",
    "MarketplaceProvider",
    "MarketplaceProviderConfig",
    "MarketplaceRateLimitError",
    "MarketplaceRegistry",
    "MarketplaceRequestError",
    "MarketplaceResult",
    "MarketplaceReturn",
    "MarketplaceSalesEstimate",
    "MarketplaceSearchResult",
    "MarketplaceShipping",
    "MarketplaceShippingOption",
]
