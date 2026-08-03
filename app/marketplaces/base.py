"""Abstract base class for all marketplace providers.

Design decisions:
- `MarketplaceProvider` is the SINGLE contract between the platform and any
  marketplace. The rest of the platform may only ever depend on this type.
- All 12 capabilities are abstract methods. A concrete provider MUST implement
  all 12 (enforced by the ABC at class-definition time).
- For capabilities a marketplace genuinely cannot provide, the provider's
  method body returns the typed model with ``supported=False`` (via
  ``_not_supported``) rather than raising. This keeps the interface complete
  AND lets the platform degrade gracefully.
- Providers declare which capabilities they do NOT support in the class
  attribute ``_unsupported_capabilities``. This drives ``capabilities()`` so
  the platform can disable UI/features accordingly and is introspectable by
  tests (enforcing the "all marketplaces implement all methods" contract).
- Methods are async for non-blocking I/O.
- `marketplace_name`/`marketplace_code`/`version` class attributes identify
  the provider. Providers are auto-discovered by subclassing this class.
- Providers receive a config dict and an optional shared HTTP client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.marketplaces.models import (
    MarketplaceBuyBox,
    MarketplaceCompetition,
    MarketplaceFees,
    MarketplaceInventory,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplacePricing,
    MarketplaceProduct,
    MarketplaceReturn,
    MarketplaceSalesEstimate,
    MarketplaceSearchResult,
    MarketplaceShipping,
)

# All capabilities exposed by the interface.
CAPABILITIES: tuple[str, ...] = (
    "search",
    "lookup",
    "pricing",
    "fees",
    "inventory",
    "orders",
    "listings",
    "competition",
    "sales_estimate",
    "buybox",
    "shipping",
    "returns",
)


class MarketplaceProvider(ABC):
    """Abstract base class that all marketplace providers must implement.

    Class attributes:
        marketplace_name: Human-readable name (e.g. "Amazon").
        marketplace_code: Short code (e.g. "amazon").
        version: Provider version string.
        _unsupported_capabilities: Capability names this provider does not
            actually support (their methods return ``supported=False``).
    """

    marketplace_name: str = ""
    marketplace_code: str = ""
    version: str = "1.0.0"
    _unsupported_capabilities: frozenset[str] = frozenset()

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            config: Marketplace-specific configuration (API keys, endpoints, etc.).
            http_client: Shared HTTP client for connection pooling.
        """
        self._config = config or {}
        self._http_client = http_client

    # ── Capability discovery ────────────────────────────────

    def capabilities(self) -> dict[str, bool]:
        """Report which of the 12 capabilities this provider actually supports.

        Returns:
            Dict mapping capability name to a supported bool.
        """
        return {
            cap: cap not in self._unsupported_capabilities for cap in CAPABILITIES
        }

    # ── The 12 required capabilities ────────────────────────

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[MarketplaceSearchResult]:
        """Search the marketplace catalog by keyword."""

    @abstractmethod
    async def lookup(self, external_id: str) -> MarketplaceProduct | None:
        """Look up a product by its marketplace identifier (ASIN/SKU/item_id)."""

    @abstractmethod
    async def pricing(self, external_id: str) -> MarketplacePricing | None:
        """Get pricing information for a product."""

    @abstractmethod
    async def fees(self, external_id: str, price: Any | None = None) -> MarketplaceFees | None:
        """Get fee structure for selling a product."""

    @abstractmethod
    async def inventory(self, external_id: str) -> MarketplaceInventory | None:
        """Get inventory/stock information."""

    @abstractmethod
    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:
        """Get recent orders from this marketplace."""

    @abstractmethod
    async def listings(self, *, status: str | None = None) -> list[MarketplaceListing]:
        """Get the seller's own listings on this marketplace."""

    @abstractmethod
    async def competition(self, external_id: str) -> MarketplaceCompetition | None:
        """Get the competitive landscape for a product."""

    @abstractmethod
    async def sales_estimate(self, external_id: str) -> MarketplaceSalesEstimate | None:
        """Estimate sales volume for a product."""

    @abstractmethod
    async def buybox(self, external_id: str) -> MarketplaceBuyBox | None:
        """Get Buy Box / featured-offer status for a product."""

    @abstractmethod
    async def shipping(
        self,
        external_id: str,
        *,
        quantity: int = 1,
        postal_code: str | None = None,
    ) -> MarketplaceShipping | None:
        """Get shipping options for a product."""

    @abstractmethod
    async def returns(self, *, limit: int = 50) -> list[MarketplaceReturn]:
        """Get recent returns from this marketplace."""

    # ── Shared helpers ──────────────────────────────────────

    def _not_supported(self, model_type: type[Any]) -> Any:
        """Return a typed, graceful 'unsupported' result.

        Args:
            model_type: One of the MarketplaceResult subclasses.

        Returns:
            An instance of model_type with ``supported=False``.
        """
        return model_type(
            marketplace=self.marketplace_code,
            supported=False,
            raw={},
        )

    def get_http_client(self) -> httpx.AsyncClient:
        """Get or create an HTTP client for this provider.

        Uses the shared client if provided, otherwise creates one.
        """
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:  # noqa: B027
        """Clean up resources. Override if the provider holds resources."""
