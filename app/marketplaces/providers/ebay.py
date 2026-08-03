"""eBay marketplace provider.

Integrates with the eBay Buy (Browse), Inventory, and Fulfillment APIs.

Design decisions:
- Search/lookup use the public Browse API (no auth) where possible.
- Inventory/orders/listings use the Inventory + Fulfillment APIs (OAuth).
- Fees, sales-estimates, and returns are not reliably exposed by a simple
  public endpoint; those capabilities degrade gracefully.
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

_BROWSE_BASE = "https://api.ebay.com/buy/browse/v1"
_INGEST_BASE = "https://api.ebay.com/sell/inventory/v1"


class EBayMarketplace(MarketplaceProvider):
    """Marketplace provider for eBay."""

    marketplace_name = "eBay"
    marketplace_code = "ebay"
    version = "1.0.0"

    _unsupported_capabilities = frozenset({"fees", "sales_estimate", "returns"})

    def __init__(self, config: dict[str, Any] | None = None, http_client: Any = None) -> None:
        super().__init__(config, http_client)
        self._browse_base = (self._config.get("browse_base_url") or _BROWSE_BASE).rstrip("/")
        self._ingest_base = (self._config.get("ingest_base_url") or _INGEST_BASE).rstrip("/")

    def _require_oauth(self) -> None:
        if not self._config.get("access_token"):
            raise MarketplaceConfigurationError(
                self.marketplace_code,
                "eBay seller API requires 'access_token'",
            )

    def _oauth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.get('access_token', '')}"}

    # ── Public Browse (no auth) ─────────────────────────────

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[MarketplaceSearchResult]:
        client = self.get_http_client()
        response = await client.get(
            f"{self._browse_base}/item_summary/search",
            params={
                "q": query,
                "limit": page_size,
                "offset": (page - 1) * page_size,
            },
        )
        response.raise_for_status()
        data = response.json()
        results: list[MarketplaceSearchResult] = []
        for item in data.get("itemSummaries", []):
            price = item.get("price", {}).get("value")
            rating = item.get("rating", [{}])
            results.append(
                MarketplaceSearchResult(
                    marketplace=self.marketplace_code,
                    external_id=item.get("itemId", ""),
                    title=item.get("title", ""),
                    image_url=item.get("image", {}).get("imageUrl") if item.get("image") else None,
                    product_url=item.get("itemWebUrl"),
                    price=self._to_decimal(price),
                    currency=item.get("price", {}).get("currency", "USD"),
                    condition=item.get("condition"),
                    seller=item.get("seller", {}).get("username") if item.get("seller") else None,
                    rating=self._to_decimal(rating[0].get("value")) if rating else None,
                    review_count=(item.get("itemHref") is not None and 0) or 0,
                    raw=item,
                )
            )
        return results

    async def lookup(self, external_id: str) -> MarketplaceProduct | None:
        client = self.get_http_client()
        response = await client.get(
            f"{self._browse_base}/item/{external_id}",
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        price = item.get("price", {}).get("value")
        images = [i.get("imageUrl") for i in item.get("image", {}).get("additionalImages", []) if i.get("imageUrl")]
        return MarketplaceProduct(
            marketplace=self.marketplace_code,
            external_id=external_id,
            title=item.get("title", ""),
            description=item.get("description"),
            category=item.get("categories", [{}])[0].get("categoryName") if item.get("categories") else None,
            images=images,
            main_image=item.get("image", {}).get("imageUrl") if item.get("image") else None,
            brand=(item.get("brand", [{}])[0].get("value") if item.get("brand") else None),
            gtin=None,
            price=self._to_decimal(price),
            currency=item.get("price", {}).get("currency", "USD"),
            condition=item.get("condition"),
            product_url=item.get("itemWebUrl"),
            raw=item,
        )

    async def pricing(self, external_id: str) -> MarketplacePricing | None:
        product = await self.lookup(external_id)
        if product is None:
            return None
        return MarketplacePricing(
            marketplace=self.marketplace_code,
            external_id=external_id,
            current_price=product.price,
            currency=product.currency,
            raw=product.raw,
        )

    async def shipping(
        self,
        external_id: str,
        *,
        quantity: int = 1,  # noqa: ARG002
        postal_code: str | None = None,  # noqa: ARG002
    ) -> MarketplaceShipping | None:
        client = self.get_http_client()
        response = await client.get(
            f"{self._browse_base}/item/{external_id}",
            params={"fieldgroups": "SHIPPING_OPTIONS"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        shipping = item.get("shippingOptions", [])
        options = [
            {
                "method": s.get("shippingServiceCode", "Standard"),
                "carrier": s.get("shippingCarrierCode"),
                "cost": self._to_decimal(s.get("shippingCost", {}).get("value")),
                "currency": s.get("shippingCost", {}).get("currency", "USD"),
                "estimated_days_min": s.get("minEstimatedDeliveryDays"),
                "estimated_days_max": s.get("maxEstimatedDeliveryDays"),
            }
            for s in shipping
        ]
        return MarketplaceShipping(
            marketplace=self.marketplace_code,
            external_id=external_id,
            options=options,
            currency=shipping[0].get("shippingCost", {}).get("currency", "USD") if shipping else "USD",
            ships_from=item.get("primaryCategoryId"),
            raw=item,
        )

    async def competition(self, external_id: str) -> MarketplaceCompetition | None:
        client = self.get_http_client()
        response = await client.get(
            f"{self._browse_base}/item/{external_id}",
            params={"fieldgroups": "COMPACT"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        price = self._to_decimal(item.get("price", {}).get("value"))
        return MarketplaceCompetition(
            marketplace=self.marketplace_code,
            external_id=external_id,
            offers=[{"seller": item.get("seller", {}).get("username"), "price": price}],
            competitive_price=price,
            currency=item.get("price", {}).get("currency", "USD"),
            offer_count=1,
            raw=item,
        )

    async def buybox(self, external_id: str) -> MarketplaceBuyBox | None:
        """eBay has no literal Buy Box; report the featured/BIN price as reference."""
        item = await self.lookup(external_id)
        if item is None or item.price is None:
            return None
        return MarketplaceBuyBox(
            marketplace=self.marketplace_code,
            external_id=external_id,
            is_winner=False,
            buy_box_price=item.price,
            currency=item.currency,
            winner_seller=None,
            raw=item.raw,
        )

    # ── Seller APIs (OAuth) ─────────────────────────────────

    async def inventory(self, external_id: str) -> MarketplaceInventory | None:
        self._require_oauth()
        client = self.get_http_client()
        response = await client.get(
            f"{self._ingest_base}/inventory_item/{external_id}",
            headers=self._oauth_headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        availability = data.get("availability", {}).get("shipToLocationAvailability", {})
        qty = availability.get("quantity", 0) or 0
        return MarketplaceInventory(
            marketplace=self.marketplace_code,
            external_id=external_id,
            quantity_available=int(qty),
            status="in_stock" if qty > 0 else "out_of_stock",
            raw=data,
        )

    async def listings(self, *, status: str | None = None) -> list[MarketplaceListing]:  # noqa: ARG002
        self._require_oauth()
        client = self.get_http_client()
        response = await client.get(
            f"{self._ingest_base}/inventory_item",
            headers=self._oauth_headers(),
            params={"limit": 100},
        )
        response.raise_for_status()
        data = response.json()
        listings: list[MarketplaceListing] = []
        for item in data.get("inventoryItems", []):
            listings.append(
                MarketplaceListing(
                    marketplace=self.marketplace_code,
                    listing_id=item.get("sku", ""),
                    external_id=item.get("sku", ""),
                    title=item.get("title", ""),
                    sku=item.get("sku"),
                    price=self._to_decimal(item.get("price", {}).get("value")),
                    currency=item.get("price", {}).get("currency", "USD"),
                    quantity=int(item.get("availability", {}).get("shipToLocationAvailability", {}).get("quantity", 0) or 0),
                    status="active",
                    raw=item,
                )
            )
        return listings

    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:
        self._require_oauth()
        client = self.get_http_client()
        response = await client.get(
            f"{self._browse_base.replace('buy/browse', 'sell/fulfillment')}/order",
            headers=self._oauth_headers(),
            params={"limit": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()
        orders: list[MarketplaceOrder] = []
        for o in data.get("orders", []):
            items = []
            for li in o.get("lineItems", []):
                items.append(
                    MarketplaceOrderItem(
                        marketplace=self.marketplace_code,
                        line_item_id=li.get("lineItemId", ""),
                        external_id=li.get("itemId", ""),
                        quantity=int(li.get("quantity", 0) or 0),
                        unit_price=self._to_decimal(li.get("lineItemCost", {}).get("value")),
                        currency=li.get("lineItemCost", {}).get("currency", "USD"),
                        raw=li,
                    )
                )
            orders.append(
                MarketplaceOrder(
                    marketplace=self.marketplace_code,
                    order_id=o.get("orderId", ""),
                    status=o.get("orderPaymentStatus"),
                    created_at=None,
                    currency="USD",
                    total_amount=self._to_decimal(o.get("total", {}).get("value")),
                    items=items,
                    raw=o,
                )
            )
        return orders

    async def fees(self, external_id: str, price: Any | None = None) -> MarketplaceFees | None:  # noqa: ARG002
        """eBay does not expose per-item fees via a simple public endpoint."""
        return self._not_supported(MarketplaceFees)

    async def sales_estimate(self, external_id: str) -> MarketplaceSalesEstimate | None:  # noqa: ARG002
        """eBay does not expose sales estimates via a public endpoint."""
        return self._not_supported(MarketplaceSalesEstimate)

    async def returns(self, *, limit: int = 50) -> list[MarketplaceReturn]:  # noqa: ARG002
        """eBay returns require the Post-Sale/Compatibility APIs; not supported here."""
        return []

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))
