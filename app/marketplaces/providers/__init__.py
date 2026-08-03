"""Marketplace provider implementations.

Each module implements a concrete `MarketplaceProvider` for a specific
marketplace. New marketplaces are added here WITHOUT modifying existing code —
drop in a module that subclasses `MarketplaceProvider` and it is auto-discovered
by the `MarketplaceRegistry`.
"""

from app.marketplaces.providers.amazon import AmazonMarketplace
from app.marketplaces.providers.ebay import EBayMarketplace
from app.marketplaces.providers.etsy import EtsyMarketplace
from app.marketplaces.providers.facebook import FacebookMarketplace
from app.marketplaces.providers.tiktok import TikTokShopMarketplace
from app.marketplaces.providers.walmart import WalmartMarketplace

__all__ = [
    "AmazonMarketplace",
    "EBayMarketplace",
    "EtsyMarketplace",
    "FacebookMarketplace",
    "TikTokShopMarketplace",
    "WalmartMarketplace",
]
