"""Concrete feature computers.

Each `FeatureComputer` is self-documenting: it declares its key, name,
description, formula (the exact method), semantic version, value type, required
signals, and refresh TTL. `compute` maps a `SignalBundle` to a value +
confidence, degrading gracefully when signals are missing (and reporting lower
confidence accordingly).

The registry auto-discovers these by importing this module. New features â€”
including future ML models â€” are added by subclassing `FeatureComputer` and
registering here.
"""

from __future__ import annotations

import math

from app.features.base import EntityContext, FeatureComputer, FeatureComputeResult
from app.features.models import FeatureValueType
from app.features.signals import SignalBundle, SignalInfo, signal_confidence


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def _used(signals: SignalBundle, keys: tuple[str, ...]) -> dict[str, SignalInfo]:
    return {k: info for k in keys if (info := signals.info(k)) is not None}


def _confidence(signals: SignalBundle, required: tuple[str, ...]) -> float:
    return signal_confidence(signals, required)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Marketplace & product-level risk / stability features
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class PriceStabilityScore(FeatureComputer):
    """How stable a product's price has been over its observed history.

    Lower coefficient of variation means more stable pricing.
    """

    key = "price_stability_score"
    name = "Price Stability Score"
    description = "1 - min(1, CV(price_history)); 1.0 = perfectly stable, 0.0 = highly volatile."
    formula = "1 - min(1, std(price_history) / mean(price_history))"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("price_history",)
    ttl_seconds = 6 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        history = [float(v) for v in (signals.get("price_history") or [])]
        if len(history) < 2:
            return FeatureComputeResult(
                value=1.0,
                confidence=_confidence(signals, self.required_signals),
                used_signals=_used(signals, self.required_signals),
                notes="Fewer than 2 price observations; no volatility observed.",
            )
        mean = sum(history) / len(history)
        if mean <= 0:
            return FeatureComputeResult(
                value=1.0,
                confidence=_confidence(signals, self.required_signals),
                used_signals=_used(signals, self.required_signals),
                notes="Non-positive mean price; treated as stable.",
            )
        cv = _std(history) / mean
        return FeatureComputeResult(
            value=round(_clamp(1.0 - min(1.0, cv)), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"n={len(history)}, cv={cv:.4f}",
        )


class BrandRiskScore(FeatureComputer):
    """Higher = riskier brand (recalls, negative reviews, risk indicators)."""

    key = "brand_risk_score"
    name = "Brand Risk Score"
    description = "0..1 risk score rising with risk indicators, negative reviews and recalls."
    formula = "clamp(0.05 + 0.2*n_indicators + 0.15*negative_reviews_rate + 0.3*recall_flag, 0, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("brand", "brand_risk_indicators", "negative_reviews_rate", "recall_flag")
    ttl_seconds = 24 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        indicators = signals.get("brand_risk_indicators") or []
        neg_rate = float(signals.get("negative_reviews_rate") or 0.0)
        recall = bool(signals.get("recall_flag") or False)
        score = 0.05 + 0.2 * len(indicators) + 0.15 * neg_rate + (0.3 if recall else 0.0)
        return FeatureComputeResult(
            value=round(_clamp(score), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"indicators={len(indicators)}, recalls={recall}",
        )


class SupplierReliabilityScore(FeatureComputer):
    """Weighted reliability of a supplier from on-time, fill, rating, incidents."""

    key = "supplier_reliability_score"
    name = "Supplier Reliability Score"
    description = "0..1 from on-time rate, fill rate, rating and incident count."
    formula = "clamp(0.4*on_time + 0.3*fill + 0.3*(rating/5) - 0.1*incidents, 0, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("supplier_on_time_rate", "supplier_fill_rate", "supplier_rating", "supplier_incidents")
    ttl_seconds = 24 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        on_time = float(signals.get("supplier_on_time_rate") or 0.9)
        fill = float(signals.get("supplier_fill_rate") or 0.9)
        rating = float(signals.get("supplier_rating") or 4.0) / 5.0
        incidents = int(signals.get("supplier_incidents") or 0)
        score = 0.4 * on_time + 0.3 * fill + 0.3 * rating - 0.1 * incidents
        return FeatureComputeResult(
            value=round(_clamp(score), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"incidents={incidents}",
        )


class CompetitionScore(FeatureComputer):
    """How contested a listing is, from competitor count and price pressure."""

    key = "competition_score"
    name = "Competition Score"
    description = "Higher = more competitive (more competitors + larger price gap to list)."
    formula = "clamp(0.3*min(1,n_competitors/10) + 0.7*price_pressure, 0, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("competitor_prices", "list_price", "buy_box_price")
    ttl_seconds = 6 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        comps = [float(v) for v in (signals.get("competitor_prices") or [])]
        count_factor = min(1.0, len(comps) / 10.0)
        list_price = signals.get("list_price")
        buy_box = signals.get("buy_box_price")
        if list_price and buy_box and float(list_price) > 0:
            pressure = _clamp((float(list_price) - float(buy_box)) / float(list_price))
        else:
            pressure = 0.5  # unknown price relationship
        score = 0.3 * count_factor + 0.7 * pressure
        return FeatureComputeResult(
            value=round(_clamp(score), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"competitors={len(comps)}",
        )


class BuyBoxStability(FeatureComputer):
    """How stable the Buy Box position is (share, price volatility, win rate)."""

    key = "buy_box_stability"
    name = "Buy Box Stability"
    description = "0..1 blending buy box share, low price volatility and win rate."
    formula = "clamp(0.5*buy_box_share + 0.3*(1-price_volatility) + 0.2*win_rate, 0, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("buy_box_share", "price_volatility", "win_rate")
    ttl_seconds = 3 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        share = float(signals.get("buy_box_share") or 0.5)
        vol = float(signals.get("price_volatility") or 0.5)
        win = float(signals.get("win_rate") or 0.5)
        score = 0.5 * share + 0.3 * (1.0 - vol) + 0.2 * win
        return FeatureComputeResult(
            value=round(_clamp(score), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


class InventoryHealth(FeatureComputer):
    """How well stocked an entity is (not understocked, not overstocked)."""

    key = "inventory_health"
    name = "Inventory Health"
    description = "1.0 when stock sits in the ideal band; lower toward stockouts or overstock."
    formula = "piecewise band scoring around [reorder_point*1.5, max_stock*0.8]"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("stock_level", "reorder_point", "max_stock", "days_of_cover", "turnover_rate")
    ttl_seconds = 6 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        stock = float(signals.get("stock_level") or 0.0)
        reorder = signals.get("reorder_point")
        max_stock = signals.get("max_stock")
        if reorder is None or max_stock is None or float(max_stock) <= 0:
            return FeatureComputeResult(
                value=0.5,
                confidence=_confidence(signals, self.required_signals),
                used_signals=_used(signals, self.required_signals),
                notes="No stock band defined; neutral.",
            )
        lo = 1.5 * float(reorder)
        hi = 0.8 * float(max_stock)
        if stock <= lo:
            score = max(0.0, stock / max(lo, 1e-9))
        elif stock >= hi:
            score = max(0.0, 1.0 - (stock - hi) / max(max_stock - hi, 1e-9))
        else:
            score = 1.0
        return FeatureComputeResult(
            value=round(_clamp(score), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"stock={stock:.2f}, ideal=[{lo:.2f},{hi:.2f}]",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Demand & velocity features
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class VelocityScore(FeatureComputer):
    """Sales velocity relative to the category average (0..1)."""

    key = "velocity_score"
    name = "Velocity Score"
    description = "Normalized sales velocity vs category average (0.5 = at average)."
    formula = "clamp(0.5*(1 + (velocity - avg)/max(avg, eps)), 0, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("sales_velocity", "category_avg_velocity")
    ttl_seconds = 6 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        vel = float(signals.get("sales_velocity") or 0.0)
        avg = float(signals.get("category_avg_velocity") or 0.0)
        score = 0.5 * (1.0 + (vel - avg) / max(avg, 1e-9))
        return FeatureComputeResult(
            value=round(_clamp(score), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


class SeasonalityScore(FeatureComputer):
    """Strength of a product's seasonal demand pattern (0..1)."""

    key = "seasonality_score"
    name = "Seasonality Score"
    description = "1 - (min_monthly_sales / max_monthly_sales); higher = more seasonal."
    formula = "clamp(1 - min(monthly_sales)/max(monthly_sales), 0, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("monthly_sales",)
    ttl_seconds = 24 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        monthly = [float(v) for v in (signals.get("monthly_sales") or [])]
        if len(monthly) < 2:
            return FeatureComputeResult(
                value=0.0,
                confidence=_confidence(signals, self.required_signals),
                used_signals=_used(signals, self.required_signals),
                notes="Fewer than 2 months of data.",
            )
        mx = max(monthly)
        mn = min(monthly)
        if mx <= 0:
            return FeatureComputeResult(
                value=0.0,
                confidence=_confidence(signals, self.required_signals),
                used_signals=_used(signals, self.required_signals),
            )
        return FeatureComputeResult(
            value=round(_clamp(1.0 - mn / mx), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"range=[{mn:.2f},{mx:.2f}]",
        )


class CouponFrequency(FeatureComputer):
    """How often coupons are offered for the entity (per 30-day window)."""

    key = "coupon_frequency"
    name = "Coupon Frequency"
    description = "Number of coupon offers normalized to a 30-day window."
    formula = "coupon_count * 30 / max(coupon_window_days, 1)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("coupon_count", "coupon_window_days")
    ttl_seconds = 12 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        count = float(signals.get("coupon_count") or 0.0)
        window = float(signals.get("coupon_window_days") or 30.0)
        freq = count * 30.0 / max(window, 1.0)
        return FeatureComputeResult(
            value=round(freq, 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


class RestockProbability(FeatureComputer):
    """Probability of stockout before the next replenishment arrives."""

    key = "restock_probability"
    name = "Restock Probability"
    description = "Likelihood stock runs out given velocity, lead time and on-hand stock."
    formula = "1/(1+exp((stock - velocity*lead_time)/spread)); bumped at reorder point"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("stock_level", "sales_velocity", "lead_time_days", "reorder_point", "demand_std")
    ttl_seconds = 6 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        stock = float(signals.get("stock_level") or 0.0)
        velocity = float(signals.get("sales_velocity") or 0.0)
        lead = float(signals.get("lead_time_days") or 0.0)
        reorder = signals.get("reorder_point")
        demand_std = signals.get("demand_std")
        expected_use = velocity * lead
        if stock <= 0:
            return FeatureComputeResult(
                value=1.0,
                confidence=_confidence(signals, self.required_signals),
                used_signals=_used(signals, self.required_signals),
                notes="No stock on hand.",
            )
        spread = float(demand_std) * math.sqrt(max(lead, 1.0)) if demand_std else max(expected_use, 1.0)
        p = 1.0 / (1.0 + math.exp((stock - expected_use) / max(spread, 1e-9)))
        if reorder is not None and stock <= float(reorder):
            p = max(p, 0.6)
        return FeatureComputeResult(
            value=round(_clamp(p), 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
            notes=f"expected_use={expected_use:.2f} over {lead:.0f}d",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Financial projection features
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class ExpectedMargin(FeatureComputer):
    """Projected unit margin (fraction; can be negative)."""

    key = "expected_margin"
    name = "Expected Margin"
    description = "(sell_price - cost - sell_price*fees - holding) / sell_price"
    formula = "(sell_price - cost - sell_price*fees_pct - holding_cost) / sell_price"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("sell_price", "cost", "fees_pct", "holding_cost")
    ttl_seconds = 3 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        sell = float(signals.get("sell_price") or 0.0)
        cost = float(signals.get("cost") or 0.0)
        fees = float(signals.get("fees_pct") or 0.0)
        holding = float(signals.get("holding_cost") or 0.0)
        margin = (sell - cost - sell * fees - holding) / sell if sell > 0 else 0.0
        return FeatureComputeResult(
            value=round(margin, 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


class ExpectedROI(FeatureComputer):
    """Projected return on invested capital (ratio)."""

    key = "expected_roi"
    name = "Expected ROI"
    description = "expected_profit / invested_capital (ratio, e.g. 0.15 = 15%)."
    formula = "expected_profit / max(invested_capital, eps)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("expected_profit", "invested_capital", "roi")
    ttl_seconds = 3 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        profit = float(signals.get("expected_profit") or 0.0)
        capital = float(signals.get("invested_capital") or 0.0)
        roi = profit / capital if capital > 0 else float(signals.get("roi") or 0.0)
        return FeatureComputeResult(
            value=round(roi, 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


class ExpectedSales(FeatureComputer):
    """Projected units sold per period from velocity, seasonality and growth."""

    key = "expected_sales"
    name = "Expected Sales"
    description = "velocity * seasonality * (1 + growth) * (1 + promotion_effect)"
    formula = "sales_velocity * seasonality_factor * (1 + demand_growth_rate) * (1 + promotion_effect)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("sales_velocity", "seasonality_factor", "demand_growth_rate", "promotion_effect")
    ttl_seconds = 6 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        vel = float(signals.get("sales_velocity") or 0.0)
        season = float(signals.get("seasonality_factor") or 1.0)
        growth = float(signals.get("demand_growth_rate") or 0.0)
        promo = float(signals.get("promotion_effect") or 0.0)
        expected = vel * max(season, 0.0) * (1.0 + growth) * (1.0 + promo)
        return FeatureComputeResult(
            value=round(expected, 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


class ExpectedTurnover(FeatureComputer):
    """Inventory turnover ratio (annual sales / average inventory)."""

    key = "expected_turnover"
    name = "Expected Turnover"
    description = "annual_sales_qty / avg_inventory_qty"
    formula = "annual_sales_qty / max(avg_inventory_qty, eps)"
    version = "1.0.0"
    value_type = FeatureValueType.NUMERIC
    required_signals = ("annual_sales_qty", "avg_inventory_qty")
    ttl_seconds = 24 * 3600

    async def compute(self, _entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        annual = float(signals.get("annual_sales_qty") or 0.0)
        avg_inv = float(signals.get("avg_inventory_qty") or 0.0)
        turnover = annual / avg_inv if avg_inv > 0 else 0.0
        return FeatureComputeResult(
            value=round(turnover, 4),
            confidence=_confidence(signals, self.required_signals),
            used_signals=_used(signals, self.required_signals),
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Registry
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


ALL_COMPUTERS: tuple[type[FeatureComputer], ...] = (
    PriceStabilityScore,
    BrandRiskScore,
    SupplierReliabilityScore,
    CompetitionScore,
    BuyBoxStability,
    InventoryHealth,
    VelocityScore,
    SeasonalityScore,
    CouponFrequency,
    RestockProbability,
    ExpectedMargin,
    ExpectedROI,
    ExpectedSales,
    ExpectedTurnover,
)


def register_computers() -> None:
    """Ensure all computers are imported/registered (registry auto-discovers)."""
    for cls in ALL_COMPUTERS:
        _ = cls  # import side-effect only
