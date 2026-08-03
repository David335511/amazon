"""Walmart Marketplace provider.

Integrates with the Walmart Marketplace APIs (Items, Pricing, Inventory,
Orders, Returns) for selling on Walmart.com.

Design decisions:
- Walmart does not expose fees, competition, sales estimates, or Buy Box via a
  simple public API; those capabilities degrade gracefully.
- Uses OAuth access-token headers driven by configuration.
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
    MarketplaceOrderItem,
    MarketplacePricing,
    MarketplaceProduct,
    MarketplaceReturn,
    MarketplaceSalesEstimate,
    MarketplaceSearchResult,
    MarketplaceShipping,
)

_BASE = "https://marketplace.walmartapis.com/v3"


class WalmartMarketplace(MarketplaceProvider):
    """Marketplace provider for Walmart Marketplace."""

    marketplace_name = "Walmart Marketplace"
    marketplace_code = "walmart"
    version = "1.0.0"

    _unsupported_capabilities = frozenset(
        {"fees", "competition", "sales_estimate", "buybox", "shipping"}
    )

    def __init__(self, config: dict[str, Any] | None = None, http_client: Any = None) -> None:
        super().__init__(config, http_client)
        self._base_url = (self._config.get("base_url") or _BASE).rstrip("/")

    def _require_credentials(self) -> None:
        if not (self._config.get("api_key") and self._config.get("access_token")):
            raise MarketplaceConfigurationError(
                self.marketplace_code,
                "Walmart requires 'api_key' (consumer id) and 'access_token'",
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.get('access_token', '')}",
            "Accept": "application/json",
        }

    # ── Items ───────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        page: int = 1,  # noqa: ARG002
        page_size: int = 20,
    ) -> list[MarketplaceSearchResult]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/items",
            headers=self._headers(),
            params={"query": query, "limit": page_size},
        )
        response.raise_for_status()
        data = response.json()
        results: list[MarketplaceSearchResult] = []
        for item in data.get("items", []):
            results.append(
                MarketplaceSearchResult(
                    marketplace=self.marketplace_code,
                    external_id=item.get("sku", ""),
                    title=item.get("title", ""),
                    brand=item.get("brand"),
                    category=item.get("category"),
                    image_url=item.get("productImageUrl"),
                    price=self._to_decimal(item.get("price", {}).get("amount") if isinstance(item.get("price"), dict) else item.get("price")),
                    currency="USD",
                    in_stock=item.get("inStock", True),
                    seller="Walmart",
                    raw=item,
                )
            )
        return results

    async def lookup(self, external_id: str) -> MarketplaceProduct | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/items/{external_id}",
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        return MarketplaceProduct(
            marketplace=self.marketplace_code,
            external_id=external_id,
            title=item.get("title", ""),
            description=item.get("description"),
            brand=item.get("brand"),
            manufacturer=item.get("manufacturer"),
            category=item.get("category"),
            images=item.get("productImages", {}).get("mainImages", [{}])[0].get("imageUrls", []) if item.get("productImages") else [],
            price=self._to_decimal(item.get("price", {}).get("amount") if isinstance(item.get("price"), dict) else item.get("price")),
            currency="USD",
            product_url=item.get("productUrl"),
            raw=item,
        )

    async def pricing(self, external_id: str) -> MarketplacePricing | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/pricing/price",
            headers=self._headers(),
            params={"sku": external_id},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        pricing = data.get("pricing", [])
        current = None
        if pricing:
            current = pricing[0].get("price", [{}])[0].get("amount") if pricing[0].get("price") else None
        return MarketplacePricing(
            marketplace=self.marketplace_code,
            external_id=external_id,
            current_price=self._to_decimal(current),
            currency="USD",
            raw=data,
        )

    async def inventory(self, external_id: str) -> MarketplaceInventory | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/inventory/{external_id}",
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        node = data.get("nodes", [{}])[0] if data.get("nodes") else {}
        qty = int(node.get("availableToSellQuantity", 0) or 0)
        return MarketplaceInventory(
            marketplace=self.marketplace_code,
            external_id=external_id,
            quantity_available=qty,
            status="in_stock" if qty > 0 else "out_of_stock",
            raw=data,
        )

    async def listings(self, *, status: str | None = None) -> list[MarketplaceListing]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/items",
            headers=self._headers(),
            params={"status": status or "PUBLISHED"},
        )
        response.raise_for_status()
        data = response.json()
        listings: list[MarketplaceListing] = []
        for item in data.get("items", []):
            listings.append(
                MarketplaceListing(
                    marketplace=self.marketplace_code,
                    listing_id=item.get("sku", ""),
                    external_id=item.get("sku", ""),
                    title=item.get("title", ""),
                    sku=item.get("sku"),
                    price=self._to_decimal(item.get("price", {}).get("amount") if isinstance(item.get("price"), dict) else item.get("price")),
                    currency="USD",
                    status=(item.get("productName") and "active") or "inactive",
                    raw=item,
                )
            )
        return listings

    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/orders",
            headers=self._headers(),
            params={"limit": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()
        orders: list[MarketplaceOrder] = []
        for o in data.get("list", {}).get("elements", []):
            items = []
            for li in o.get("orderLines", {}).get("orderLine", []):
                items.append(
                    MarketplaceOrderItem(
                        marketplace=self.marketplace_code,
                        line_item_id=li.get("lineNumber", ""),
                        external_id=li.get("item", {}).get("sku", ""),
                        quantity=int(li.get("orderLineQuantity", {}).get("amount", 0) or 0),
                        unit_price=self._to_decimal(li.get("orderLineQuantity", {}).get("unitOfMeasure")),
                        raw=li,
                    )
                )
            orders.append(
                MarketplaceOrder(
                    marketplace=self.marketplace_code,
                    order_id=o.get("purchaseOrderId", ""),
                    status=o.get("orderSummary", {}).get("orderStatus"),
                    total_amount=self._to_decimal(o.get("orderSummary", {}).get("orderAmount", {}).get("amount")),
                    currency="USD",
                    items=items,
                    raw=o,
                )
            )
        return orders

    async def returns(self, *, limit: int = 50) -> list[MarketplaceReturn]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/returns",
            headers=self._headers(),
            params={"limit": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()
        returns: list[MarketplaceReturn] = []
        for r in data.get("returns", []):
            returns.append(
                MarketplaceReturn(
                    marketplace=self.marketplace_code,
                    return_id=r.get("returnOrderId", ""),
                    order_id=r.get("purchaseOrderId", ""),
                    external_id=r.get("customerOrderId", ""),
                    status=r.get("status"),
                    reason=r.get("returnLabel", {}).get("labelCode"),
                    currency="USD",
                    refund_amount=self._to_decimal(r.get("totalRefundAmount", {}).get("amount")),
                    raw=r,
                )
            )
        return returns

    async def fees(self, external_id: str, price: Any | None = None) -> MarketplaceFees | None:  # noqa: ARG002
        return self._not_supported(MarketplaceFees)

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

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))
