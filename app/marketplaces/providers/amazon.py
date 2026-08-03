"""Amazon marketplace provider.

Integrates with the Amazon Selling Partner API (SP-API) for product catalog,
pricing, fees, inventory, orders, listings, competition, and Buy Box data.

Design decisions:
- Amazon is NOT hardcoded anywhere else in the platform. All Amazon-specific
  logic and endpoints live in this provider only.
- Sales-estimate data is not exposed by SP-API; this capability degrades
  gracefully (``supported=False``) and can be backed by a third-party data
  provider (e.g. Keepa) behind this same interface later.
- Credentials come from configuration: LWA client id/secret + refresh token.
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
    MarketplaceShippingOption,
)

_SPAPI_BASE = "https://sellingpartnerapi-na.amazon.com"


class AmazonMarketplace(MarketplaceProvider):
    """Marketplace provider for Amazon (via Selling Partner API)."""

    marketplace_name = "Amazon"
    marketplace_code = "amazon"
    version = "1.0.0"

    _unsupported_capabilities = frozenset({"sales_estimate"})

    def __init__(self, config: dict[str, Any] | None = None, http_client: Any = None) -> None:
        super().__init__(config, http_client)
        self._base_url = (self._config.get("base_url") or _SPAPI_BASE).rstrip("/")
        self._marketplace_id = self._config.get("marketplace_id") or "ATVPDKIKX0DER"  # US
        self._seller_id = self._config.get("store_id") or ""

    def _require_credentials(self) -> None:
        if not (self._config.get("api_key") and self._config.get("refresh_token")):
            raise MarketplaceConfigurationError(
                self.marketplace_code,
                "Amazon SP-API requires 'api_key' and 'refresh_token'",
            )

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "x-amz-access-token": access_token,
            "x-amz-marketplace-id": self._marketplace_id,
            "Content-Type": "application/json",
        }

    # ── Product catalog ─────────────────────────────────────

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
            f"{self._base_url}/catalog/2022-04-01/items",
            headers=self._headers(self._config.get("access_token", "")),
            params={
                "keywords": query,
                "pageSize": page_size,
                "pageToken": str(page),
                "marketplaceIds": self._marketplace_id,
            },
        )
        response.raise_for_status()
        data = response.json()

        results: list[MarketplaceSearchResult] = []
        for item in data.get("items", []):
            identifiers = item.get("identifiers", [])
            asin = identifiers[0].get("asin") if identifiers else ""
            attributes = item.get("attributes", {})
            price_attrs = attributes.get("list_price", [{}])
            price = price_attrs[0].get("value", None) if price_attrs else None
            results.append(
                MarketplaceSearchResult(
                    marketplace=self.marketplace_code,
                    external_id=asin,
                    title=(attributes.get("title", [{}])[0].get("value", "") if attributes.get("title") else ""),
                    brand=(attributes.get("brand", [{}])[0].get("value") if attributes.get("brand") else None),
                    category=(attributes.get("product_type", [{}])[0].get("value") if attributes.get("product_type") else None),
                    image_url=(attributes.get("main_image", [{}])[0].get("value") if attributes.get("main_image") else None),
                    price=self._to_decimal(price),
                    currency="USD",
                    condition="New",
                    raw=item,
                )
            )
        return results

    async def lookup(self, external_id: str) -> MarketplaceProduct | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/catalog/2022-04-01/items/{external_id}",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceIds": self._marketplace_id, "includeChildCatalogData": "true"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        attributes = item.get("attributes", {})
        price_attrs = attributes.get("list_price", [{}])
        price = price_attrs[0].get("value") if price_attrs else None
        images = [i.get("value") for i in attributes.get("main_image", []) if i.get("value")]
        return MarketplaceProduct(
            marketplace=self.marketplace_code,
            external_id=external_id,
            title=(attributes.get("title", [{}])[0].get("value", "") if attributes.get("title") else ""),
            description=(attributes.get("item_description", [{}])[0].get("value") if attributes.get("item_description") else None),
            brand=(attributes.get("brand", [{}])[0].get("value") if attributes.get("brand") else None),
            manufacturer=(attributes.get("manufacturer", [{}])[0].get("value") if attributes.get("manufacturer") else None),
            category=(attributes.get("product_type", [{}])[0].get("value") if attributes.get("product_type") else None),
            images=images,
            main_image=images[0] if images else None,
            upc=self._first_identifier(item, "upc"),
            ean=self._first_identifier(item, "ean"),
            model_number=self._first_identifier(item, "part_number"),
            price=self._to_decimal(price),
            currency="USD",
            condition="New",
            raw=item,
        )

    # ── Pricing & competition ───────────────────────────────

    async def pricing(self, external_id: str) -> MarketplacePricing | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/products/pricing/v0/price",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceId": self._marketplace_id, "asins": external_id, "itemType": "Asin"},
        )
        response.raise_for_status()
        data = response.json()
        payload = (data.get("payload") or [{}])[0]
        product = payload.get("Product") or {}
        price_info = product.get("CompetitivePricing", {}).get("Price") or {}
        listing = price_info.get("ListingPrice", {}).get("Amount")
        return MarketplacePricing(
            marketplace=self.marketplace_code,
            external_id=external_id,
            current_price=self._to_decimal(listing),
            currency="USD",
            raw=payload,
        )

    async def fees(self, external_id: str, price: Any | None = None) -> MarketplaceFees | None:
        self._require_credentials()
        client = self.get_http_client()
        price = price if price is not None else Decimal("0")
        body = {
            "FeesEstimateRequest": {
                "MarketplaceId": self._marketplace_id,
                "Identifier": external_id,
                "PriceType": "ExclusiveTax",
                "PriceToEstimateFees": {"ListingPrice": {"Amount": str(price), "CurrencyCode": "USD"}},
            }
        }
        response = await client.post(
            f"{self._base_url}/products/fees/v0/items/{external_id}/feesEstimate",
            headers=self._headers(self._config.get("access_token", "")),
            json=body,
        )
        response.raise_for_status()
        data = response.json()
        estimate = data.get("payload", {}).get("FeesEstimate", {})
        total = estimate.get("TotalFeesEstimate", {}).get("Amount")
        breakdown = estimate.get("FeeBreakdown", [])
        referral = next((f.get("FeeAmount", {}).get("Amount") for f in breakdown if f.get("FeeType") == "ReferralFee"), None)
        fba = next((f.get("FeeAmount", {}).get("Amount") for f in breakdown if f.get("FeeType") == "FBAFees"), None)
        return MarketplaceFees(
            marketplace=self.marketplace_code,
            external_id=external_id,
            referral_fee=self._to_decimal(referral),
            fulfillment_fee=self._to_decimal(fba),
            fee_total=self._to_decimal(total),
            currency="USD",
            raw=data,
        )

    async def competition(self, external_id: str) -> MarketplaceCompetition | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/products/pricing/v0/competitivePrice",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceId": self._marketplace_id, "asins": external_id, "itemType": "Asin"},
        )
        response.raise_for_status()
        data = response.json()
        payload = data.get("payload") or []
        offers: list[dict[str, Any]] = []
        for p in payload:
            product = p.get("Product") or {}
            for offer in product.get("CompetitivePricing", {}).get("CompetitivePrices", []):
                offers.append(offer.get("Price") or {})
        return MarketplaceCompetition(
            marketplace=self.marketplace_code,
            external_id=external_id,
            offers=[
                {
                    "seller": o.get("SellerId"),
                    "price": self._to_decimal(o.get("ListingPrice", {}).get("Amount")),
                    "currency": "USD",
                    "is_fulfilled_by_platform": o.get("Shipping", {}).get("IsFulfilledByAmazon", False),
                }
                for o in offers
            ],
            competitive_price=self._to_decimal(min(
                (o.get("ListingPrice", {}).get("Amount") for o in offers if o.get("ListingPrice", {}).get("Amount")),
                default=None,
            )) if offers else None,
            offer_count=len(offers),
            currency="USD",
            raw=data,
        )

    async def buybox(self, external_id: str) -> MarketplaceBuyBox | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/products/pricing/v0/listingOffers/{external_id}",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceId": self._marketplace_id, "ItemCondition": "New"},
        )
        response.raise_for_status()
        data = response.json()
        offers = data.get("payload", {}).get("Offers", [])
        winner = next((o for o in offers if o.get("IsBuyBoxWinner")), None)
        return MarketplaceBuyBox(
            marketplace=self.marketplace_code,
            external_id=external_id,
            is_winner=winner is not None,
            buy_box_price=self._to_decimal((winner or {}).get("ListingPrice", {}).get("Amount")),
            currency="USD",
            winner_seller=(winner or {}).get("SellerId"),
            is_fulfilled_by_platform=(winner or {}).get("IsFulfilledByAmazon", False),
            offer_count=len(offers),
            raw=data,
        )

    # ── Inventory & fulfillment ─────────────────────────────

    async def inventory(self, external_id: str) -> MarketplaceInventory | None:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/fba/inventory/v1/summaries",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceIds": self._marketplace_id, "granularityType": "Marketplace", "skus": external_id},
        )
        response.raise_for_status()
        data = response.json()
        summary = (data.get("payload", {}).get("inventorySummaries") or [{}])[0]
        qty = summary.get("totalQuantity") or 0
        return MarketplaceInventory(
            marketplace=self.marketplace_code,
            external_id=external_id,
            quantity_available=qty,
            quantity_inbound=summary.get("inboundWorkingQuantity", 0) + summary.get("inboundShippedQuantity", 0),
            status="in_stock" if qty > 0 else "out_of_stock",
            raw=data,
        )

    # ── Orders & listings & returns ─────────────────────────

    async def orders(self, *, limit: int = 50) -> list[MarketplaceOrder]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/orders/v0/orders",
            headers=self._headers(self._config.get("access_token", "")),
            params={"MarketplaceIds": self._marketplace_id, "MaxResultsPerPage": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()
        orders: list[MarketplaceOrder] = []
        for o in data.get("payload", {}).get("Orders", []):
            items = [
                MarketplaceOrderItem(
                    marketplace=self.marketplace_code,
                    external_id=o.get("AmazonOrderId", ""),
                    quantity=int(o.get("NumberOfItemsUnshipped", 0) or 0),
                    currency="USD",
                )
            ]
            orders.append(
                MarketplaceOrder(
                    marketplace=self.marketplace_code,
                    order_id=o.get("AmazonOrderId", ""),
                    status=o.get("OrderStatus"),
                    currency="USD",
                    total_amount=self._to_decimal(o.get("OrderTotal", {}).get("Amount")),
                    items=items,
                    fulfillment_channel=o.get("FulfillmentChannel"),
                    raw=o,
                )
            )
        return orders

    async def listings(self, *, status: str | None = None) -> list[MarketplaceListing]:  # noqa: ARG002
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/listings/2021-08-01/items/{self._seller_id}",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceIds": self._marketplace_id},
        )
        response.raise_for_status()
        data = response.json()
        listings: list[MarketplaceListing] = []
        for item in data.get("items", []):
            listings.append(
                MarketplaceListing(
                    marketplace=self.marketplace_code,
                    listing_id=item.get("sku", ""),
                    external_id=item.get("productType", ""),
                    title=item.get("productType", ""),
                    sku=item.get("sku"),
                    status="active",
                    raw=item,
                )
            )
        return listings

    async def returns(self, *, limit: int = 50) -> list[MarketplaceReturn]:
        self._require_credentials()
        client = self.get_http_client()
        response = await client.get(
            f"{self._base_url}/fba/fulfillmentReturns/v1/returns",
            headers=self._headers(self._config.get("access_token", "")),
            params={"marketplaceIds": self._marketplace_id, "maxResultsPerPage": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()
        returns: list[MarketplaceReturn] = []
        for r in data.get("payload", {}).get("Returns", []):
            returns.append(
                MarketplaceReturn(
                    marketplace=self.marketplace_code,
                    return_id=r.get("ReturnAuthorizationId", ""),
                    order_id=r.get("OrderId", ""),
                    external_id=r.get("SellerSKU", ""),
                    status=r.get("ReturnRequestStatus"),
                    reason=r.get("ReturnReason"),
                    currency="USD",
                    refund_amount=self._to_decimal(r.get("RefundAmount")),
                    raw=r,
                )
            )
        return returns

    # ── Shipping ────────────────────────────────────────────

    async def shipping(
        self,
        external_id: str,
        *,
        quantity: int = 1,  # noqa: ARG002
        postal_code: str | None = None,  # noqa: ARG002
    ) -> MarketplaceShipping | None:
        """Best-effort shipping info.

        SP-API does not expose per-product shipping options directly; we return
        a default Prime/FBA estimate driven by configuration.
        """
        self._require_credentials()
        return MarketplaceShipping(
            marketplace=self.marketplace_code,
            external_id=external_id,
            options=[
                MarketplaceShippingOption(
                    marketplace=self.marketplace_code,
                    method="Standard",
                    carrier="Amazon",
                    cost=None,
                    currency="USD",
                    estimated_days_min=2,
                    estimated_days_max=5,
                ),
                MarketplaceShippingOption(
                    marketplace=self.marketplace_code,
                    method="Prime",
                    carrier="Amazon",
                    cost=None,
                    currency="USD",
                    estimated_days_min=1,
                    estimated_days_max=2,
                ),
            ],
            free_shipping_threshold=None,
            ships_from=self._config.get("ships_from"),
            currency="USD",
        )

    async def sales_estimate(self, external_id: str) -> MarketplaceSalesEstimate | None:  # noqa: ARG002
        """Sales estimates require third-party data (e.g. Keepa); not supported."""
        return self._not_supported(MarketplaceSalesEstimate)

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _first_identifier(item: dict[str, Any], key: str) -> str | None:
        identifiers = item.get("identifiers", [])
        for id_block in identifiers:
            identifier = id_block.get(key) or id_block.get(key.upper())
            if identifier:
                return identifier
        return None

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))
