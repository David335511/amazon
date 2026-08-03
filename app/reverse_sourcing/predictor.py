"""Discount prediction seam for reverse sourcing.

`DiscountPredictor` produces a predicted future discount depth (0..1) for a
supplier's discount history. Pluggable — a real forecasting model / LLM can be
wired behind the same interface. The default is a deterministic, stdlib-only
trend extrapolation (recent mean + one-period slope), clamped to 0..1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class DiscountPredictor(ABC):
    """Predict the next-period discount depth from a historical series."""

    @abstractmethod
    def predict(self, supplier_code: str, asin: str, discounts: list[float]) -> float | None:
        """Return a predicted discount depth (0..1), or None if not enough data."""


class TrendDiscountPredictor(DiscountPredictor):
    """Pure-stdlib prediction: recent mean plus one-period linear trend."""

    def predict(self, supplier_code: str, asin: str, discounts: list[float]) -> float | None:  # noqa: ARG002 (base signature)
        if not discounts:
            return None
        series = discounts[-20:]
        n = len(series)
        mean = sum(series) / n
        if n == 1:
            return _clamp01(mean)
        xs = list(range(n))
        mx = (n - 1) / 2.0
        my = mean
        denom = sum((x - mx) ** 2 for x in xs)
        slope = 0.0
        if denom:
            slope = sum(
                (x - mx) * (y - my) for x, y in zip(xs, series, strict=True)
            ) / denom
        return _clamp01(mean + slope)
