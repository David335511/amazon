"""Core abstractions for supplier intelligence.

A supplier is scored purely from its **historical** observation series — we
never judge a supplier on a live snapshot, only on the accumulated record of
its behaviour over time. Each `SupplierObservation` is one period snapshot
(prices, sales, coupons, inventory, shipping, returns, service, cancellations,
discounts, stockouts). Scores are computed on demand over the full history, so
they never go stale and always reflect everything we know.
"""

from __future__ import annotations

from enum import StrEnum


class SupplierScore(StrEnum):
    """The five supplier scores computed from historical observations."""

    RELIABILITY = "reliability"   # how dependable the supplier is
    VOLATILITY = "volatility"     # how unstable its behaviour is (higher = worse)
    DISCOUNT = "discount"         # how favourable its discount behaviour is
    RISK = "risk"                 # overall downside (higher = worse)
    SEASONALITY = "seasonality"   # how seasonal / periodic its pricing is


# The dimensions we track per observation (mirrors the tracked-metrics surface).
TRACKED_METRICS: list[str] = [
    "historical_prices",
    "sale_frequency",
    "coupon_frequency",
    "inventory_stability",
    "shipping_speed",
    "return_policy",
    "customer_service",
    "order_cancellation_rate",
    "discount_patterns",
    "stockout_frequency",
]
