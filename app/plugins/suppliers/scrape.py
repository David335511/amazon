"""Generic browser-based supplier plugin.

Demonstrates how supplier plugins use the browser automation framework instead
of implementing browser automation themselves. This plugin crawls a configured
retailer website with the shared `Crawler`, which provides rate limiting,
retries, CAPTCHA detection, proxy rotation, sessions, screenshots and HTML
archiving for free.

The plugin is configuration-driven: it takes URL templates and simple field
extraction rules in its config, so it can target many retailers without code
changes. For production it would be specialized per retailer, but the crawler
integration shown here is the pattern every browser-based supplier should follow.
"""

from __future__ import annotations

import re
from typing import Any

from app.plugins.base import BaseSupplierPlugin
from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierInventory,
    SupplierPricing,
    SupplierProductLookup,
    SupplierProductSearchResult,
    SupplierShipping,
)


class ScrapePlugin(BaseSupplierPlugin):
    """Configuration-driven browser-based supplier plugin."""

    supplier_name = "Web Scrape"
    supplier_code = "scrape"
    version = "1.0.0"

    async def search(
        self,
        query: str,
        *,
        page: int = 1,  # noqa: ARG002 - part of the fixed plugin interface
        page_size: int = 20,
    ) -> list[SupplierProductSearchResult]:
        """Search the configured retailer by navigating to its search URL."""
        crawler = self.get_crawler()
        search_url = self._config.get("search_url", "").format(query=query)
        result = await crawler.fetch(search_url, use_pool=True)
        if result.blocked or not result.text:
            return []

        pattern = self._config.get("search_item_pattern", r"(?P<title>.{3,80})")
        results: list[SupplierProductSearchResult] = []
        for m in re.finditer(pattern, result.text):
            results.append(
                SupplierProductSearchResult(
                    supplier_sku=str(abs(hash(m.group("title"))))[:12],
                    title=m.group("title").strip(),
                    image_url=None,
                    price=None,
                    currency="USD",
                    in_stock=True,
                    raw={"title": m.group("title").strip()},
                )
            )
        return results[:page_size]

    async def lookup(
        self,
        sku: str,
    ) -> SupplierProductLookup | None:
        """Look up a product by navigating to its product page."""
        crawler = self.get_crawler()
        product_url = self._config.get("product_url", "").format(sku=sku)
        result = await crawler.fetch(
            product_url,
            session=self._config.get("session", f"scrape-{sku}"),
            screenshot=bool(self._config.get("screenshot", False)),
            archive=bool(self._config.get("archive", False)),
        )
        if result.blocked or not result.text:
            return None

        title = self._extract(result.text, "title")
        return SupplierProductLookup(
            supplier_sku=sku,
            title=title,
            description=self._extract(result.text, "description"),
            category=self._extract(result.text, "category"),
            price=self._parse_price(self._extract(result.text, "price")),
            currency="USD",
            raw={"url": result.final_url, "status": result.status},
        )

    async def pricing(self, sku: str) -> SupplierPricing | None:
        """Get pricing by reusing the lookup path."""
        lookup = await self.lookup(sku)
        if lookup is None:
            return None
        return SupplierPricing(
            unit_price=lookup.price,
            currency=lookup.currency,
            quantity_tiers=[],
            map_price=None,
            suggested_retail=None,
            raw=lookup.raw,
        )

    async def inventory(self, sku: str) -> SupplierInventory | None:
        """Report availability as inferred from the product page."""
        lookup = await self.lookup(sku)
        if lookup is None:
            return None
        return SupplierInventory(
            supplier_sku=sku,
            quantity_available=1 if lookup.price else 0,
            quantity_inbound=0,
            is_backorderable=False,
            raw=lookup.raw,
        )

    async def shipping(
        self,
        sku: str,  # noqa: ARG002 - part of the fixed plugin interface
        *,
        quantity: int = 1,  # noqa: ARG002
        postal_code: str | None = None,  # noqa: ARG002
    ) -> SupplierShipping | None:
        return SupplierShipping(methods=[], free_shipping_threshold=None, raw={})

    async def coupon(self, code: str | None = None) -> list[SupplierCoupon]:  # noqa: ARG002
        return []

    async def availability(self, sku: str) -> SupplierAvailability | None:
        lookup = await self.lookup(sku)
        if lookup is None:
            return None
        return SupplierAvailability(
            supplier_sku=sku,
            is_available=bool(lookup.price),
            backorder_allowed=False,
            stock_status="in_stock" if lookup.price else "out_of_stock",
            raw=lookup.raw,
        )

    # ── Helpers ─────────────────────────────────────────────

    def _extract(self, text: str | None, field: str) -> str | None:
        """Extract a field from page text using config regex patterns."""
        if not text:
            return None
        patterns = self._config.get("extract_patterns") or {}
        pattern = patterns.get(field)
        if not pattern:
            return None
        m = re.search(pattern, text)
        return m.group(1).strip() if m and m.groups() else (m.group(0).strip() if m else None)

    @staticmethod
    def _parse_price(value: Any) -> Any:
        from decimal import Decimal
        if not value:
            return None
        cleaned = re.sub(r"[^0-9.]", "", str(value))
        try:
            return Decimal(cleaned)
        except Exception:
            return None
