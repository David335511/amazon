"""Etsy marketplace provider.

Integrates with the Etsy Open API v3 for listing search, product details,
pricing, fees, orders, and listings.

Design decisions:
- Etsy does not expose a Buy Box, competitive offers, sales estimates, or
  inventory quantities via a public API; those capabilities degrade gracefully.
- Etsy fees are computed from the listing price using configurable fee rates
  (transaction fee %, payment processing fee) since Etsy publishes fixed rates.
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

_BASE = "https://openapi.etsy.com/v3/application"


class EtsyMarketplace(MarketplaceProvider):
    """Marketplace provider for Etsy."""

    marketplace_name = "Etsy"
    marketplace_code = "etsy"
    version = "1.0.0"

    _unsupported_capabilities = frozenset(
        {"inventory", "competition", "sales_estimate", "buybox", "shipping", "returns"}
    )

    def __init__(self, config: dict[str, Any] | None = None, http_client: Any = None) -> None:
        super().__init__(config, http_client)
        self._base_url = (self._config.get("base_url") or _BASE).rstrip("/")
        self._shop_id = self._config.get("store_id") or ""

    def _require_credentials(self) -> None:
        if not self._config.get("api_key"):
            raise MarketplaceConfigurationError(
                self.marketplace_code,
                "Etsy requires 'api_key' (keystring)",
            )

    def _headers(self) -> dict[str, str]:
        headers = {"x-api-key": self._config.get("api_key", "")}
        if self._config.get("access_token"):
            headers["Authorization"] = f"Bearer {self._config.get('access_token')}"
        return headers

    def _fee_rates(self) -> dict[str, float]:
        extra = self._config.get("extra", {})
        return {
            "transaction_fee_pct": float(extra.get("transaction_fee_pct", 6.5)),
            "payment_fee_pct": float(extra.get("payment_fee_pct", 3.0)),
            "payment_fee_fixed": float(extra.get("payment_fee_fixed", 0.25)),
        }

    # ── Public listing data ─────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[MarketplaceSearchResult]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/listings/active",
            headers=self._headers(),
            params={"keywords": query, "limit": page_size, "offset": (page - 1) * page_size},
        )
        response.raise_for_status()
        data = response.json()
        results: list[MarketplaceSearchResult] = []
        for item in data.get("results", []):
            price = item.get("price")
            results.append(
                MarketplaceSearchResult(
                    marketplace=self.marketplace_code,
                    external_id=str(item.get("listing_id", "")),
                    title=item.get("title", ""),
                    category=item.get("taxonomy_path", [""])[-1] if item.get("taxonomy_path") else None,
                    image_url=(item.get("images", [{}])[0].get("url_570xN") if item.get("images") else None),
                    product_url=item.get("url"),
                    price=self._to_decimal(price),
                    currency=item.get("currency_code", "USD"),
                    condition="New",
                    in_stock=True,
                    seller=item.get("shop_name"),
                    raw=item,
                )
            )
        return results

    async def lookup(self, external_id: str) -> MarketplaceProduct | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/listings/{external_id}",
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        images = [i.get("url_fullxfull") for i in item.get("images", []) if i.get("url_fullxfull")]
        return MarketplaceProduct(
            marketplace=self.marketplace_code,
            external_id=external_id,
            title=item.get("title", ""),
            description=item.get("description"),
            category=item.get("taxonomy_path", [""])[-1] if item.get("taxonomy_path") else None,
            images=images,
            main_image=images[0] if images else None,
            price=self._to_decimal(item.get("price")),
            currency=item.get("currency_code", "USD"),
            product_url=item.get("url"),
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

    async def fees(self, external_id: str, price: Any | None = None) -> MarketplaceFees | None:
        if price is None:
            product = await self.lookup(external_id)
            price = product.price if product else Decimal("0")
        price = self._to_decimal(price) or Decimal("0")
        rates = self._fee_rates()
        referral = (price * Decimal(str(rates["transaction_fee_pct"])) / Decimal("100")).quantize(Decimal("0.01"))
        processing = (
            price * Decimal(str(rates["payment_fee_pct"])) / Decimal("100")
            + Decimal(str(rates["payment_fee_fixed"]))
        ).quantize(Decimal("0.01"))
        return MarketplaceFees(
            marketplace=self.marketplace_code,
            external_id=external_id,
            referral_fee=referral,
            payment_processing_fee=processing,
            fee_total=(referral + processing).quantize(Decimal("0.01")),
            currency="USD",
            raw={"fee_rates": rates, "price": str(price)},
        )

    # ── Seller data ─────────────────────────────────────────

    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/shops/{self._shop_id}/receipts",
            headers=self._headers(),
            params={"limit": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()
        orders: list[MarketplaceOrder] = []
        for r in data.get("results", []):
            items = []
            for li in r.get("transactions", []):
                items.append(
                    MarketplaceOrderItem(
                        marketplace=self.marketplace_code,
                        line_item_id=str(li.get("transaction_id", "")),
                        external_id=str(li.get("listing_id", "")),
                        sku=li.get("product_data", {}).get("sku") if li.get("product_data") else None,
                        quantity=int(li.get("quantity", 0) or 0),
                        unit_price=self._to_decimal(li.get("price")),
                        raw=li,
                    )
                )
            orders.append(
                MarketplaceOrder(
                    marketplace=self.marketplace_code,
                    order_id=str(r.get("receipt_id", "")),
                    status=(r.get("is_shipped") and "shipped") or "open",
                    total_amount=self._to_decimal(r.get("grandtotal")),
                    currency=r.get("currency_code", "USD"),
                    items=items,
                    raw=r,
                )
            )
        return orders

    async def listings(self, *, status: str | None = None) -> list[MarketplaceListing]:
        self._require_credentials()
        client = self.get_http_client()
        endpoint = "active" if status in (None, "active") else status
        response = await client.get(
            f"{self._base_url}/shops/{self._shop_id}/listings/{endpoint}",
            headers=self._headers(),
            params={"limit": 100},
        )
        response.raise_for_status()
        data = response.json()
        listings: list[MarketplaceListing] = []
        for item in data.get("results", []):
            listings.append(
                MarketplaceListing(
                    marketplace=self.marketplace_code,
                    listing_id=str(item.get("listing_id", "")),
                    external_id=str(item.get("listing_id", "")),
                    title=item.get("title", ""),
                    price=self._to_decimal(item.get("price")),
                    currency=item.get("currency_code", "USD"),
                    quantity=int(item.get("quantity", 0) or 0),
                    status="active" if item.get("state") == "active" else item.get("state"),
                    product_url=item.get("url"),
                    raw=item,
                )
            )
        return listings

    # ── Unsupported capabilities ────────────────────────────

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
