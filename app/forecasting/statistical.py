"""Statistical forecasting models — pure standard library.

Each model extrapolates a numeric time series and produces a point prediction,
a 95% confidence interval and a confidence score. All are target-agnostic:
every `ForecastTarget` is represented as a numeric series, so these models work
for price, ROI, profit, inventory, sales, Buy Box probability and competition.

The ensemble treats these as its base members. Each is a small, explainable,
deterministic model.
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
)

Z95 = 1.96


def _window_from_metadata(ctx: ForecastContext, default: int) -> int:
    raw = ctx.metadata.get("window")
    if raw and raw.isdigit():
        return max(1, int(raw))
    return default


def _alpha_from_metadata(ctx: ForecastContext, default: float) -> float:
    raw = ctx.metadata.get("alpha")
    if raw:
        try:
            return max(0.01, min(1.0, float(raw)))
        except ValueError:
            pass
    return default


def _period_from_metadata(ctx: ForecastContext, default: int) -> int:
    raw = ctx.metadata.get("season_period")
    if raw and raw.isdigit():
        return max(2, int(raw))
    return default


def _base(
    ctx: ForecastContext,
    model_name: str,
    method: str,
    version: str,
    prediction: float,
    std: float,
    explanation: str,
) -> ForecastResult:
    lower, upper = forecast_interval(prediction, std)
    return ForecastResult(
        model_name=model_name,
        method=method,
        version=version,
        target=ctx.target,
        horizon=ctx.horizon,
        prediction=prediction,
        lower=lower,
        upper=upper,
        confidence=clamp01(1.0 - (std / max(abs(prediction), 1e-9))),
        explanation=explanation,
    )


class MovingAverageModel(ForecastModel):
    """Rolling-window mean with a standard-error confidence interval."""

    name = "moving_average"
    method = "Simple moving average with rolling standard-deviation confidence interval"
    version = "1.0.0"
    family = "statistical"

    def __init__(self, window: int | None = None) -> None:
        self.window = window

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        n = len(ctx.series)
        window = min(self.window or _window_from_metadata(ctx, 3), n)
        hist = ctx.series[-window:]
        prediction = series_mean(hist)
        std = series_std(hist)
        se = std / math.sqrt(window) if window and std else 0.0
        return _base(
            ctx,
            self.name,
            self.method,
            self.version,
            prediction,
            se,
            (
                f"{self.method}. Window={window} of {n} observations, "
                f"mean={prediction:.4g}, std={std:.4g}."
            ),
        )


class ExponentialSmoothingModel(ForecastModel):
    """Single exponential smoothing (level-following)."""

    name = "exponential_smoothing"
    method = "Single exponential smoothing: level = alpha*value + (1-alpha)*level"
    version = "1.0.0"
    family = "statistical"

    def __init__(self, alpha: float | None = None) -> None:
        self.alpha = alpha

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        alpha = self.alpha or _alpha_from_metadata(ctx, 0.3)
        series = ctx.series
        level = series[0]
        for v in series[1:]:
            level = alpha * v + (1 - alpha) * level
        prediction = level
        # SES understates variance; widen the interval slightly.
        std = series_std(series) * 1.25
        return _base(
            ctx,
            self.name,
            self.method,
            self.version,
            prediction,
            std,
            (
                f"{self.method}. alpha={alpha:.2g}, final level={prediction:.4g}, "
                f"{len(series)} observations."
            ),
        )


class LinearTrendModel(ForecastModel):
    """Ordinary-least-squares linear trend extrapolation."""

    name = "linear_trend"
    method = "Ordinary-least-squares linear trend extrapolation"
    version = "1.0.0"
    family = "statistical"

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        xs = list(range(len(ctx.series)))
        ys = ctx.series
        n = len(ys)
        mean_x = (n - 1) / 2.0
        mean_y = series_mean(ys)
        denom = sum((x - mean_x) ** 2 for x in xs)
        slope = 0.0
        if denom:
            slope = sum(
                (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
            ) / denom
        intercept = mean_y - slope * mean_x
        future_x = (n - 1) + ctx.horizon
        prediction = intercept + slope * future_x
        residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=True)]
        resid_std = series_std(residuals) or abs(prediction) * 0.1
        se = resid_std * math.sqrt(
            1 + 1.0 / n + ((future_x - mean_x) ** 2) / max(denom, 1e-9)
        )
        return _base(
            ctx,
            self.name,
            self.method,
            self.version,
            prediction,
            se,
            (
                f"{self.method}. slope={slope:.4g}/period, intercept={intercept:.4g}, "
                f"forecast at t+{ctx.horizon}={prediction:.4g}, n={n}."
            ),
        )


class SeasonalAverageModel(ForecastModel):
    """Level of the most recent complete seasonal cycle."""

    name = "seasonal_average"
    method = "Average of the most recent complete seasonal cycle"
    version = "1.0.0"
    family = "statistical"

    def __init__(self, period: int | None = None) -> None:
        self.period = period

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        period = self.period or _period_from_metadata(ctx, 7)
        series = ctx.series
        cycle = series[-period:] if len(series) >= period else series
        prediction = series_mean(cycle)
        std = series_std(cycle) or series_std(series) * 0.5
        return _base(
            ctx,
            self.name,
            self.method,
            self.version,
            prediction,
            std,
            (
                f"{self.method}. period={period}, level={prediction:.4g} over "
                f"{len(cycle)} points."
            ),
        )


class PersistenceModel(ForecastModel):
    """Naive no-change baseline — the last observed value."""

    name = "persistence"
    method = "Naive no-change baseline (last observed value)"
    version = "1.0.0"
    family = "statistical"

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        series = ctx.series
        prediction = series[-1]
        std = series_std(series) or abs(prediction) * 0.1
        return _base(
            ctx,
            self.name,
            self.method,
            self.version,
            prediction,
            std,
            f"{self.method}. Last observed value={prediction:.4g} (n={len(series)}).",
        )
