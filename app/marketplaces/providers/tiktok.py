"""TikTok Shop marketplace provider.

Integrates with the TikTok Shop Partner API for product, inventory, order, and
return/refund management.

Design decisions:
- TikTok Shop does not expose public catalog search/pricing/competition/Buy Box
  APIs; those capabilities degrade gracefully.
- Seller operations (inventory, orders, listings, returns) use the Partner API
  with an access token and shop cipher from configuration.
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

_BASE = "https://open-api.tiktokglobalshop.com"


class TikTokShopMarketplace(MarketplaceProvider):
    """Marketplace provider for TikTok Shop."""

    marketplace_name = "TikTok Shop"
    marketplace_code = "tiktok"
    version = "1.0.0"

    _unsupported_capabilities = frozenset(
        {"search", "lookup", "pricing", "fees", "competition", "sales_estimate", "buybox", "shipping"}
    )

    def __init__(self, config: dict[str, Any] | None = None, http_client: Any = None) -> None:
        super().__init__(config, http_client)
        self._base_url = (self._config.get("base_url") or _BASE).rstrip("/")
        self._shop_id = self._config.get("store_id") or ""

    def _require_credentials(self) -> None:
        if not (self._config.get("api_key") and self._config.get("access_token")):
            raise MarketplaceConfigurationError(
                self.marketplace_code,
                "TikTok Shop requires 'api_key' (app key) and 'access_token'",
            )

    def _headers(self) -> dict[str, str]:
        return {
            "x-tts-access-token": self._config.get("access_token", ""),
            "Content-Type": "application/json",
        }

    def _shop(self) -> dict[str, Any]:
        return {"shop_cipher": self._shop_id}

    async def inventory(self, external_id: str) -> MarketplaceInventory | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.post(
            f"{self._base_url}/inventory/202406/stock/query",
            headers=self._headers(),
            json={"shop_cipher": self._shop_id, "skus": [external_id]},
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        sku = (data.get("skus") or [{}])[0]
        qty = int(sku.get("stock", {}).get("available", 0) or 0)
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
        response = await client.post(
            f"{self._base_url}/product/202309/products/search",
            headers=self._headers(),
            json={
                "shop_cipher": self._shop_id,
                "page_size": 50,
                "status": status,
            },
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        listings: list[MarketplaceListing] = []
        for p in data.get("products", []):
            listings.append(
                MarketplaceListing(
                    marketplace=self.marketplace_code,
                    listing_id=p.get("id", ""),
                    external_id=p.get("id", ""),
                    title=p.get("title", ""),
                    sku=p.get("skus", [{}])[0].get("sku_code") if p.get("skus") else None,
                    price=self._to_decimal((p.get("skus", [{}])[0].get("price") or {}).get("sell_price") if p.get("skus") else None),
                    currency="USD",
                    quantity=int((p.get("skus", [{}])[0].get("stock_infos", [{}])[0].get("available_stock") or 0) if p.get("skus") else 0),
                    status=p.get("status"),
                    raw=p,
                )
            )
        return listings

    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.post(
            f"{self._base_url}/order/202309/orders/search",
            headers=self._headers(),
            json={
                "shop_cipher": self._shop_id,
                "page_size": min(limit, 100),
                "sort_order": "DESC",
            },
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        orders: list[MarketplaceOrder] = []
        for o in data.get("orders", []):
            items = []
            for item in o.get("items", []):
                items.append(
                    MarketplaceOrderItem(
                        marketplace=self.marketplace_code,
                        external_id=item.get("product_id", ""),
                        sku=item.get("sku_id", ""),
                        quantity=int(item.get("quantity", 0) or 0),
                        unit_price=self._to_decimal(item.get("sku_amount")),
                        raw=item,
                    )
                )
            orders.append(
                MarketplaceOrder(
                    marketplace=self.marketplace_code,
                    order_id=o.get("id", ""),
                    status=o.get("status"),
                    total_amount=self._to_decimal(o.get("payment_info", {}).get("total_amount")),
                    currency="USD",
                    items=items,
                    raw=o,
                )
            )
        return orders

    async def returns(self, *, limit: int = 50) -> list[MarketplaceReturn]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.post(
            f"{self._base_url}/return_refund/202309/return_orders/search",
            headers=self._headers(),
            json={"shop_cipher": self._shop_id, "page_size": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        returns: list[MarketplaceReturn] = []
        for r in data.get("return_orders", []):
            returns.append(
                MarketplaceReturn(
                    marketplace=self.marketplace_code,
                    return_id=r.get("return_order_id", ""),
                    order_id=r.get("order_id", ""),
                    external_id=r.get("item_ids", [""])[0] if r.get("item_ids") else "",
                    status=r.get("status"),
                    currency="USD",
                    refund_amount=self._to_decimal(r.get("refund_amount")),
                    raw=r,
                )
            )
        return returns

    # ── Unsupported capabilities ────────────────────────────

    async def search(self, query: str, *, page: int = 1, page_size: int = 20) -> list[MarketplaceSearchResult]:  # noqa: ARG002
        return []

    async def lookup(self, external_id: str) -> MarketplaceProduct | None:  # noqa: ARG002
        return self._not_supported(MarketplaceProduct)

    async def pricing(self, external_id: str) -> MarketplacePricing | None:  # noqa: ARG002
        return self._not_supported(MarketplacePricing)

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
