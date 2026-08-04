"""Retailer providers — parse raw SerpApi payloads into normalized models.

Design decisions:
- Each provider knows the exact shape SerpApi returns for its engine.
- Parsing is defensive: third-party payloads vary, so every field uses .get()
  with defaults and never raises on missing/odd data.
- A single normalized RetailerProduct is produced regardless of retailer so the
  sourcing engine and service can treat all providers uniformly.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.logging import get_logger
from app.integrations.retailers.models import (
    RetailerPrice,
    RetailerProduct,
    RetailerProvider,
    RetailerRating,
)

logger = get_logger(__name__)


def _to_decimal(value: Any) -> Decimal | None:
    """Best-effort conversion to Decimal, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        # Drop trailing currency codes like "USD"
        cleaned = re.sub(r"\s+(USD|CAD|MXN)\s*$", "", cleaned, flags=re.IGNORECASE)
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value)
        return int(digits) if digits else 0
    return 0


def _nested(value: Any, *keys: str, default: Any = None) -> Any:
    """Walk nested dicts, returning default when a key is missing."""
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key, default)
        else:
            return default
    return value


class WalmartProvider:
    """Parses SerpApi ``walmart_product`` responses."""

    engine: str = "walmart_product"
    provider = RetailerProvider.WALMART

    @staticmethod
    def parse(raw: dict[str, Any], product_id: str) -> RetailerProduct:
        results = _product_block(raw)

        price = _price_from_block(results)

        rating_dict = results.get("rating")
        rating = (
            _extract_rating(rating_dict)
            if isinstance(rating_dict, dict)
            else RetailerRating(
                rating=_to_decimal(rating_dict), review_count=_to_int(results.get("reviews"))
            )
        )

        brand = results.get("brand")
        brand_name = brand.get("name") if isinstance(brand, dict) else (brand or None)

        seller_count = _seller_count(results)

        images = results.get("images") or []
        first_image = _first_image(images)

        return RetailerProduct(
            provider=RetailerProvider.WALMART,
            product_id=product_id,
            title=results.get("title"),
            brand=brand_name,
            model_number=results.get("model_number"),
            upc=results.get("upc"),
            sku=results.get("store_sku_number"),
            url=results.get("link") or results.get("product_link"),
            price=price,
            rating=rating,
            availability=results.get("availability"),
            in_stock=results.get("in_stock"),
            seller_count=seller_count,
            image=first_image,
            raw_data=raw,
        )


class HomeDepotProvider:
    """Parses SerpApi ``home_depot_product`` responses."""

    engine: str = "home_depot_product"
    provider = RetailerProvider.HOME_DEPOT

    @staticmethod
    def parse(raw: dict[str, Any], product_id: str) -> RetailerProduct:
        results = _product_block(raw)

        price = _price_from_block(results)

        rating_dict = results.get("rating")
        rating = (
            _extract_rating(rating_dict)
            if isinstance(rating_dict, dict)
            else RetailerRating(
                rating=_to_decimal(rating_dict), review_count=_to_int(results.get("reviews"))
            )
        )

        brand = results.get("brand")
        brand_name = brand.get("name") if isinstance(brand, dict) else (brand or None)

        images = results.get("images") or []
        first_image = _first_image(images)

        return RetailerProduct(
            provider=RetailerProvider.HOME_DEPOT,
            product_id=product_id,
            title=results.get("title"),
            brand=brand_name,
            model_number=results.get("model_number"),
            upc=results.get("upc"),
            sku=results.get("store_sku_number"),
            url=results.get("link") or results.get("product_link"),
            price=price,
            rating=rating,
            availability=results.get("availability_type"),
            in_stock=_availability_in_stock(results.get("availability_type")),
            image=first_image,
            raw_data=raw,
        )


# ═══════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════


def _product_block(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the product block from a SerpApi response.

    SerpApi product engines name the payload ``product_result`` (singular); some
    documented samples use ``product_results``. Accept either defensively.
    """
    block = raw.get("product_result")
    if not isinstance(block, dict):
        block = raw.get("product_results")
    return block if isinstance(block, dict) else {}


def _price_from_block(results: dict[str, Any]) -> RetailerPrice:
    """Extract a RetailerPrice from a product block.

    Real Walmart/Home Depot payloads nest pricing under ``price_map``
    (``price``, ``was_price.price``, ``currency``). Fall back to a ``price``
    dict or a bare numeric value where ``price_map`` is absent.
    """
    price_map = results.get("price_map")
    if isinstance(price_map, dict):
        current = _to_decimal(price_map.get("price", price_map.get("unit_price")))
        original = None
        was_price = price_map.get("was_price")
        if isinstance(was_price, dict):
            original = _to_decimal(was_price.get("price"))
        currency = price_map.get("currency") or "USD"
        return RetailerPrice(
            current=current,
            original=original,
            currency=str(currency).upper(),
        )

    price_dict = results.get("price")
    if isinstance(price_dict, dict):
        return _extract_price(price_dict)
    return RetailerPrice(current=_to_decimal(price_dict))


def _extract_price(price_dict: dict[str, Any]) -> RetailerPrice:
    """Extract a RetailerPrice from a SerpApi price dict.

    SerpApi price dicts commonly use ``value``/``original`` or ``price``.
    """
    current = _to_decimal(
        price_dict.get("value", price_dict.get("price")),
    )
    original = _to_decimal(price_dict.get("original", price_dict.get("list_price")))
    currency = str(price_dict.get("currency") or price_dict.get("currency_code") or "USD")
    return RetailerPrice(current=current, original=original, currency=currency.upper())


def _extract_rating(rating_dict: dict[str, Any]) -> RetailerRating:
    """Extract a RetailerRating from a SerpApi rating dict."""
    rating = _to_decimal(rating_dict.get("value", rating_dict.get("rating")))
    return RetailerRating(
        rating=rating,
        review_count=_to_int(rating_dict.get("reviews", rating_dict.get("review_count"))),
    )


def _seller_count(results: dict[str, Any]) -> int | None:
    """Best-effort seller/offer count from a SerpApi product block."""
    offers = results.get("offers")
    if isinstance(offers, list):
        return len(offers) or None
    sellers = results.get("sellers")
    if isinstance(sellers, int):
        return sellers
    if isinstance(sellers, list):
        return len(sellers) or None
    if isinstance(sellers, dict):
        count = sellers.get("total", sellers.get("count", sellers.get("seller_count")))
        if count is not None:
            return _to_int(count)
        return len(sellers) or None
    count = results.get("seller_count")
    return _to_int(count) if count is not None else None


def _first_image(images: Any) -> str | None:
    """Extract the first usable image URL from a SerpApi images structure."""
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, str):
                return entry
            if isinstance(entry, list) and entry:
                if isinstance(entry[0], str):
                    return entry[0]
                if isinstance(entry[0], dict):
                    url = entry[0].get("url") or entry[0].get("thumbnail")
                    if url:
                        return url
    return None


def _availability_in_stock(availability: str | None) -> bool | None:
    """Infer in-stock from an availability status string."""
    if not availability:
        return None
    lowered = availability.lower()
    if "out of stock" in lowered or "discontinued" in lowered or "unavailable" in lowered:
        return False
    if "available" in lowered or "in stock" in lowered:
        return True
    return None
