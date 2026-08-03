"""LLM-reasoning forecasting model.

A `ForecastModel` whose prediction blends the series statistics with qualitative
context and whose explanation reads like a reasoning narrative. By default it is
fully deterministic (provider ``reasoning``) so it works with zero external
dependencies and is testable. A real LLM provider (e.g. OpenAI / Anthropic) can
be wired to the same interface by implementing a provider that synthesizes the
same inputs and returns a `ForecastResult`.
"""

from __future__ import annotations

import math

from app.forecasting.base import (
    ForecastContext,
    ForecastModel,
    ForecastResult,
    clamp01,
    forecast_interval,
    series_mean,
    series_std,
    trend_slope,
)

Z95 = 1.96

_TRUE_VALUES = ("1", "true", "yes", "on")


def _flag(ctx: ForecastContext, key: str) -> bool:
    return ctx.metadata.get(key, "").lower() in _TRUE_VALUES


class LLMReasoningModel(ForecastModel):
    """LLM-style reasoning over statistics, trend, volatility and context."""

    name = "llm_reasoning"
    method = "LLM-style reasoning: blends trend, level, volatility and qualitative context"
    version = "1.0.0"
    family = "llm"

    @classmethod
    def available(cls, config) -> bool:
        return config.enable_llm

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        series = ctx.series
        n = len(series)
        mean = series_mean(series)
        std = series_std(series)
        slope = trend_slope(series)

        # Point: level + extrapolated trend, adjusted by qualitative context.
        prediction = mean + slope * ctx.horizon
        notes: list[str] = []
        if _flag(ctx, "promotion_expected"):
            prediction *= 1.10
            notes.append("a promotion is expected to lift the series ~10%")
        if _flag(ctx, "supply_disruption"):
            prediction *= 0.90
            notes.append("a supply disruption is expected to depress it ~10%")

        horizon_scaled_std = max(std * math.sqrt(ctx.horizon), 1e-9)
        lower, upper = forecast_interval(prediction, horizon_scaled_std)

        direction = "rising" if slope > std * 0.25 else ("falling" if slope < -std * 0.25 else "flat")
        volatility = "high" if std > mean * 0.5 else ("moderate" if std > mean * 0.2 else "low")

        reasoning = (
            f"Analyzing {n} observations, the series is generally {direction} "
            f"({slope:+.4g}/period) with {volatility} volatility (std {std:.4g}, "
            f"mean {mean:.4g}). The point forecast {prediction:.4g} projects the "
            f"current level and trend {ctx.horizon} period(s) ahead"
        )
        if notes:
            reasoning += ", adjusted because " + " and ".join(notes)
        reasoning += ". The 95% interval widens with the horizon to reflect compounding uncertainty."

        return ForecastResult(
            model_name=self.name,
            method=self.method,
            version=self.version,
            target=ctx.target,
            horizon=ctx.horizon,
            prediction=prediction,
            lower=lower,
            upper=upper,
            confidence=clamp01(1.0 - (horizon_scaled_std / max(abs(prediction), 1e-9))),
            explanation=reasoning,
        )
