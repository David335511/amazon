"""Pure scoring and explanation for supplier intelligence.

All math here is deterministic and standard-library only (unit-testable). It
computes the five supplier scores from a historical observation series and
synthesizes a human-readable "AI" explanation of supplier behaviour.

Everything is historical: scores are functions of the full stored observation
series for a supplier, never of a single live snapshot.
"""

from __future__ import annotations

from datetime import datetime
from statistics import pstdev
from typing import Any

from app.supplier_intel.base import SupplierScore
from app.supplier_intel.config import SupplierIntelConfig
from app.supplier_intel.models import SupplierObservation


def _sort_key(o: SupplierObservation) -> datetime:
    return o.observed_at or datetime.min


# ──────────────────────────────────────────────────────────────
# Small numeric helpers (standard library)
# ──────────────────────────────────────────────────────────────


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cv(xs: list[float]) -> float:
    """Coefficient of variation (0.0 for empty / single / zero-mean series)."""
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    if m == 0.0:
        return 0.0
    return pstdev(xs) / abs(m)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _inverse_ratio(avg: float, maxval: float) -> float:
    """Credit for staying under a threshold: 1 - avg/max, clamped to 0..1."""
    if maxval <= 0:
        return 0.0
    return _clamp(1.0 - avg / maxval)


def _weighted(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights, strict=True)) / total


def _confidence(n: int, config: SupplierIntelConfig) -> float:
    return _clamp(n / max(config.min_samples, 1), 0.05, 1.0)


# ──────────────────────────────────────────────────────────────
# Composite scores
# ──────────────────────────────────────────────────────────────


def _seasonality(series: list[float]) -> dict[str, Any]:
    """Seasonal strength of a price series (pure stdlib).

    Groups observations by phase (position % period) for each candidate period
    and measures the fraction of total variance explained by the group means
    (1 - within_ss / total_ss). The best period wins. Returns score / period /
    explained / confidence.
    """
    n = len(series)
    if n < 4:
        return {"score": 0.0, "period": None, "explained": 0.0, "confidence": 0.05}
    mean_s = _mean(series)
    total_ss = sum((x - mean_s) ** 2 for x in series)
    if total_ss == 0:
        return {"score": 0.0, "period": None, "explained": 0.0, "confidence": 0.6}

    best = 0.0
    best_period: int | None = None
    for period in range(2, n // 2 + 1):
        groups: dict[int, list[float]] = {}
        for i, x in enumerate(series):
            groups.setdefault(i % period, []).append(x)
        within_ss = 0.0
        for group in groups.values():
            gm = _mean(group)
            within_ss += sum((x - gm) ** 2 for x in group)
        explained = 1.0 - (within_ss / total_ss)
        if explained > best:
            best = explained
            best_period = period

    confidence = _clamp(n / 8.0, 0.05, 1.0)
    return {
        "score": _clamp(best),
        "period": best_period,
        "explained": round(best, 4),
        "confidence": confidence,
    }


def compute_scores(
    observations: list[SupplierObservation],
    config: SupplierIntelConfig,
) -> dict[str, dict[str, Any]]:
    """Compute the five supplier scores from a historical observation series.

    Returns ``{score_name: {"value": 0..1, "confidence": 0..1, "components": {}}}``
    for every `SupplierScore`. The input is the full stored history — the
    result reflects everything observed, never a live snapshot.
    """
    obs = sorted(observations, key=_sort_key)
    n = len(obs)
    confidence = _confidence(n, config)

    empty: dict[str, dict[str, Any]] = {
        s.value: {"value": 0.0, "confidence": 0.05, "components": {}} for s in SupplierScore
    }
    if not obs:
        return empty

    prices = [o.price for o in obs]
    inv = [o.inventory_level for o in obs]
    shipping = [o.shipping_days for o in obs]
    intra = [o.inventory_variance for o in obs]
    cancels = [o.order_cancellation_rate for o in obs]
    service = [o.customer_service_score for o in obs]
    returns = [o.return_policy_score for o in obs]
    discounts = [o.discount_depth for o in obs]
    stockouts = [float(o.stockouts) for o in obs]
    coupons = [float(o.coupon_events) for o in obs]
    sales = [float(o.sale_events) for o in obs]

    avg_shipping = _mean(shipping)
    avg_stockouts = _mean(stockouts)
    avg_cancels = _mean(cancels)
    avg_service = _mean(service)
    avg_returns = _mean(returns)
    avg_discount = _mean(discounts)
    avg_coupons = _mean(coupons)
    avg_sales = _mean(sales)

    # Inventory stability combines cross-period CV with intra-period variance.
    inv_cv = _cv(inv)
    rel_intra = _mean(intra) / max(_mean(inv), 1e-9)
    stability_dev = (inv_cv + rel_intra) / (2 * config.volatility_scale)

    # ── Reliability (higher = more dependable) ──
    shipping_ok = _inverse_ratio(avg_shipping, config.max_shipping_days)
    inventory_ok = _clamp(1.0 - stability_dev)
    stockout_ok = _inverse_ratio(avg_stockouts, config.max_stockout_rate)
    cancel_ok = _clamp(1.0 - avg_cancels)
    reliability = _weighted(
        [shipping_ok, inventory_ok, stockout_ok, cancel_ok, avg_service, avg_returns],
        config.weights["reliability"],
    )

    # ── Volatility (higher = more unstable / worse) ──
    price_vol = _clamp(_cv(prices) / config.volatility_scale)
    inv_vol = _clamp(stability_dev)
    ship_vol = _clamp(_cv(shipping) / config.volatility_scale)
    stockout_swing = _clamp(1.0 - stockout_ok)  # frequent stockouts = instability
    volatility = _weighted(
        [price_vol, inv_vol, ship_vol, stockout_swing],
        config.weights["volatility"],
    )

    # ── Discount (higher = more favourable / frequent promotions) ──
    coupon_ok = _clamp(avg_coupons / max(config.max_coupon_rate, 1e-9))
    sale_ok = _clamp(avg_sales / max(config.max_sale_rate, 1e-9))
    discount = _weighted(
        [avg_discount, coupon_ok, sale_ok],
        config.weights["discount"],
    )

    # ── Risk (higher = worse) ──
    ship_slow = _clamp(1.0 - shipping_ok)
    weak_service = _clamp(1.0 - avg_service)
    weak_returns = _clamp(1.0 - avg_returns)
    risk = _weighted(
        [volatility, stockout_swing, avg_cancels, ship_slow, weak_service, weak_returns],
        config.weights["risk"],
    )

    # ── Seasonality (from the price series) ──
    season = _seasonality(prices)

    return {
        SupplierScore.RELIABILITY.value: {
            "value": reliability,
            "confidence": confidence,
            "components": {
                "shipping": round(shipping_ok, 4),
                "inventory": round(inventory_ok, 4),
                "stockout": round(stockout_ok, 4),
                "cancellation": round(cancel_ok, 4),
                "customer_service": round(avg_service, 4),
                "return_policy": round(avg_returns, 4),
            },
        },
        SupplierScore.VOLATILITY.value: {
            "value": volatility,
            "confidence": confidence,
            "components": {
                "price_cv": round(price_vol, 4),
                "inventory": round(inv_vol, 4),
                "shipping": round(ship_vol, 4),
                "stockout_swing": round(stockout_swing, 4),
            },
        },
        SupplierScore.DISCOUNT.value: {
            "value": discount,
            "confidence": confidence,
            "components": {
                "avg_discount_depth": round(avg_discount, 4),
                "coupon_frequency": round(coupon_ok, 4),
                "sale_frequency": round(sale_ok, 4),
            },
        },
        SupplierScore.RISK.value: {
            "value": risk,
            "confidence": confidence,
            "components": {
                "volatility": round(volatility, 4),
                "stockout_swing": round(stockout_swing, 4),
                "cancellation": round(avg_cancels, 4),
                "slow_shipping": round(ship_slow, 4),
                "weak_service": round(weak_service, 4),
                "weak_returns": round(weak_returns, 4),
            },
        },
        SupplierScore.SEASONALITY.value: {
            "value": season["score"],
            "confidence": season["confidence"],
            "components": {
                "best_period": season["period"],
                "explained_variance": season["explained"],
            },
        },
    }


# ──────────────────────────────────────────────────────────────
# Metric summary + AI explanation
# ──────────────────────────────────────────────────────────────


def summarize(
    observations: list[SupplierObservation],
    config: SupplierIntelConfig,
) -> dict[str, Any]:
    """Aggregate summary of the tracked metrics over the observation history."""
    obs = sorted(observations, key=_sort_key)
    if not obs:
        return {"sample_count": 0}

    prices = [o.price for o in obs]
    inv = [o.inventory_level for o in obs]
    shipping = [o.shipping_days for o in obs]
    stockouts = [float(o.stockouts) for o in obs]
    coupons = [float(o.coupon_events) for o in obs]
    sales = [float(o.sale_events) for o in obs]

    first = obs[0].observed_at
    last = obs[-1].observed_at
    span_days = 0
    if first and last:
        span_days = max(0, int((last - first).days))

    return {
        "sample_count": len(obs),
        "periods_covered_days": span_days,
        "avg_price": round(_mean(prices), 4),
        "price_cv": round(_cv(prices), 4),
        "avg_inventory_level": round(_mean(inv), 4),
        "inventory_cv": round(_cv(inv), 4),
        "avg_shipping_days": round(_mean(shipping), 4),
        "avg_stockouts_per_period": round(_mean(stockouts), 4),
        "stockout_frequency": round(
            _mean(stockouts) / max(config.max_stockout_rate, 1e-9), 4
        ),
        "avg_order_cancellation_rate": round(
            _mean([o.order_cancellation_rate for o in obs]), 4
        ),
        "avg_customer_service_score": round(
            _mean([o.customer_service_score for o in obs]), 4
        ),
        "avg_return_policy_score": round(_mean([o.return_policy_score for o in obs]), 4),
        "avg_discount_depth": round(_mean([o.discount_depth for o in obs]), 4),
        "coupon_frequency": round(_mean(coupons) / max(config.max_coupon_rate, 1e-9), 4),
        "sale_frequency": round(_mean(sales) / max(config.max_sale_rate, 1e-9), 4),
    }


def explain(
    scores: dict[str, dict[str, Any]],
    metrics: dict[str, Any],
) -> str:
    """Deterministic "AI" narrative explaining supplier behaviour.

    Blends the five scores and the historical metric summary into a readable
    reasoning narrative. This is a seam: a real LLM provider can synthesize the
    same inputs behind the same interface.
    """
    rel = scores["reliability"]["value"]
    vol = scores["volatility"]["value"]
    disc = scores["discount"]["value"]
    risk = scores["risk"]["value"]
    season = scores["seasonality"]["value"]
    period = scores["seasonality"]["components"].get("best_period")
    n = metrics.get("sample_count", 0)

    parts: list[str] = []

    if rel >= 0.7:
        parts.append(
            f"Based on {n} historical period(s), this supplier is highly reliable "
            f"({rel:.2f}) — dependable shipping, stable inventory and low cancellations."
        )
    elif rel >= 0.4:
        parts.append(
            f"Based on {n} historical period(s), reliability is moderate ({rel:.2f}); "
            "watch for inconsistent shipping or occasional stockouts."
        )
    else:
        parts.append(
            f"Based on {n} historical period(s), reliability is low ({rel:.2f}) — "
            "frequent stockouts, slow shipping or high cancellations."
        )

    if vol >= 0.6:
        parts.append(
            f"Behavioural volatility is high ({vol:.2f}); price and inventory levels "
            "swing widely across periods."
        )
    elif vol >= 0.3:
        parts.append(
            f"Behavioural volatility is moderate ({vol:.2f}); some instability in "
            "price, inventory or shipping."
        )
    else:
        parts.append(f"Behaviour is stable across periods (volatility {vol:.2f}).")

    if disc >= 0.5:
        parts.append(
            f"Discount activity is aggressive ({disc:.2f}) — frequent, deep "
            "promotions that matter for margin planning."
        )
    elif disc >= 0.25:
        parts.append(f"Discount activity is moderate ({disc:.2f}); occasional promotions.")
    else:
        parts.append(f"Discount activity is light ({disc:.2f}); pricing stays firm.")

    if risk >= 0.6:
        parts.append(
            f"Overall risk is elevated ({risk:.2f}); consider a backup supplier."
        )
    elif risk >= 0.3:
        parts.append(f"Overall risk is moderate ({risk:.2f}); manageable with monitoring.")
    else:
        parts.append(f"Overall risk is low ({risk:.2f}).")

    if season >= 0.5 and period:
        parts.append(
            f"A strong seasonal pattern (~{period}-period cycle, strength "
            f"{season:.2f}) suggests buying ahead of recurring demand peaks."
        )
    elif n >= 4:
        parts.append(
            f"No strong seasonality detected (strength {season:.2f}); demand looks "
            "steady year-round."
        )

    return " ".join(parts)
