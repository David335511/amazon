"""Facebook Marketplace provider.

Facebook Marketplace has NO public commerce API for third-party selling at the
time of writing. The Graph API (Commerce Manager) supports limited product and
order management, but product search/pricing/competition/Buy Box are not exposed.

Design decisions:
- This provider is a first-class `MarketplaceProvider` that degrades gracefully:
  it implements the full interface but reports most capabilities as unsupported
  and returns empty/``supported=False`` results for them.
- Listings and orders are best-effort Graph API calls guarded by configuration.
- This keeps the platform API uniform; when Facebook opens a commerce API, only
  this provider needs to change.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.marketplaces.base import MarketplaceProvider
from app.marketplaces.errors import MarketplaceConfigurationError
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

_GRAPH_BASE = "https://graph.facebook.com/v19.0"


class FacebookMarketplace(MarketplaceProvider):
    """Marketplace provider for Facebook Marketplace."""

    marketplace_name = "Facebook Marketplace"
    marketplace_code = "facebook"
    version = "1.0.0"

    _unsupported_capabilities = frozenset(
        {
            "search", "lookup", "pricing", "fees", "inventory",
            "competition", "sales_estimate", "buybox", "shipping", "returns",
        }
    )

    def __init__(self, config: dict[str, Any] | None = None, http_client: Any = None) -> None:
        super().__init__(config, http_client)
        self._graph_base = (self._config.get("base_url") or _GRAPH_BASE).rstrip("/")
        self._page_id = self._config.get("store_id") or ""

    def _require_credentials(self) -> None:
        if not (self._config.get("access_token") and self._page_id):
            raise MarketplaceConfigurationError(
                self.marketplace_code,
                "Facebook requires 'access_token' and 'store_id' (page_id)",
            )

    def _params(self, **extra: Any) -> dict[str, Any]:
        return {"access_token": self._config.get("access_token", ""), **extra}

    async def listings(self, *, status: str | None = None) -> list[MarketplaceListing]:  # noqa: ARG002
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._graph_base}/{self._page_id}/commerce_product_catalog_products",
            params=self._params(fields="id,title,retailer_id,price,status"),
        )
        if response.status_code in (400, 404):
            # Graph API endpoint may be unavailable/unsupported for this page.
            return []
        response.raise_for_status()
        data = response.json()
        listings: list[MarketplaceListing] = []
        for p in data.get("data", []):
            price = p.get("price")
            listings.append(
                MarketplaceListing(
                    marketplace=self.marketplace_code,
                    listing_id=p.get("id", ""),
                    external_id=p.get("retailer_id", p.get("id", "")),
                    title=p.get("title", ""),
                    price=self._to_decimal(price),
                    currency="USD",
                    status=p.get("status"),
                    raw=p,
                )
            )
        return listings

    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:  # noqa: ARG002
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._graph_base}/{self._page_id}/commerce_orders",
            params=self._params(fields="id,order_status,created,amount"),
        )
        if response.status_code in (400, 404):
            return []
        response.raise_for_status()
        data = response.json()
        orders: list[MarketplaceOrder] = []
        for o in data.get("data", []):
            amount = o.get("amount", {})
            orders.append(
                MarketplaceOrder(
                    marketplace=self.marketplace_code,
                    order_id=o.get("id", ""),
                    status=o.get("order_status"),
                    total_amount=self._to_decimal(amount.get("value")),
                    currency=amount.get("currency", "USD"),
                    raw=o,
                )
            )
        return orders

    # ── Unsupported capabilities ────────────────────────────

    async def search(self, query: str, *, page: int = 1, page_size: int = 20) -> list[MarketplaceSearchResult]:  # noqa: ARG002
        return []

    async def lookup(self, external_id: str) -> MarketplaceProduct | None:  # noqa: ARG002
        return self._not_supported(MarketplaceProduct)

    async def pricing(self, external_id: str) -> MarketplacePricing | None:  # noqa: ARG002
        return self._not_supported(MarketplacePricing)

    async def fees(self, external_id: str, price: Any | None = None) -> MarketplaceFees | None:  # noqa: ARG002
        return self._not_supported(MarketplaceFees)

    async def inventory(self, external_id: str) -> MarketplaceInventory | None:  # noqa: ARG002
        return self._not_supported(MarketplaceInventory)

    async def competition(self, external_id: str) -> MarketplaceCompetition | None:  # noqa: ARG002
        return self._not_supported(MarketplaceCompetition)

    async def sales_estimate(self, external_id: str) -> MarketplaceSalesEstimate | None:  # noqa: ARG002
        return self._not_supported(MarketplaceSalesEstimate)

    async def buybox(self, external_id: str) -> MarketplaceBuyBox | None:  # noqa: ARG002
        return self._not_supported(MarketplaceBuyBox)

    async def shipping(
        self,
        external_id: str,  # noqa: ARG002
        *,
        quantity: int = 1,  # noqa: ARG002
        postal_code: str | None = None,  # noqa: ARG002
    ) -> MarketplaceShipping | None:
        return self._not_supported(MarketplaceShipping)

    async def returns(self, *, limit: int = 50) -> list[MarketplaceReturn]:  # noqa: ARG002
        return []

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))
