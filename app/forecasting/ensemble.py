"""Ensemble forecasting — combines member models by inverse-variance weighting.

The ensemble runs every member model, weights each by the inverse of its
variance (derived from the width of its confidence interval), and produces a
weighted point forecast, a pooled confidence interval and an explanation that
lists the members and their contributions. It is itself a `ForecastModel`, so
it composes like any other model and can be used standalone or nested.
"""

from __future__ import annotations

import math

from app.forecasting.base import (
    Z95,
    ForecastContext,
    ForecastModel,
    ForecastResult,
    clamp01,
)
from app.forecasting.errors import ForecastUnavailableError


class EnsembleModel(ForecastModel):
    """Inverse-variance weighted combination of member models."""

    name = "ensemble"
    method = "Inverse-variance weighted combination of member models"
    version = "1.0.0"
    family = "ensemble"

    def __init__(self, members: list[ForecastModel]) -> None:
        self._members = members

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        members = [m for m in self._members if ctx.target in m.supports]
        if not members:
            raise ForecastUnavailableError(
                self.name, f"no member supports target {ctx.target.value!r}"
            )

        results = [m.forecast(ctx) for m in members]

        variances = []
        weights = []
        for r in results:
            width = max(r.upper - r.lower, 1e-9)
            variance = (width / (2 * Z95)) ** 2
            variances.append(variance)
            weights.append(1.0 / max(variance, 1e-9))
        wsum = sum(weights)

        prediction = (
            sum(w * r.prediction for w, r in zip(weights, results, strict=True)) / wsum
        )
        pooled_var = sum(
            (w**2) * var for w, var in zip(weights, variances, strict=True)
        ) / (wsum**2)
        pooled_std = math.sqrt(pooled_var)
        lower = prediction - Z95 * pooled_std
        upper = prediction + Z95 * pooled_std

        confidence = clamp01(
            sum(w * r.confidence for w, r in zip(weights, results, strict=True)) / wsum
        )

        members_desc = "; ".join(
            f"{r.model_name}={r.prediction:.4g} (w={w / wsum:.2f})"
            for w, r in zip(weights, results, strict=True)
        )
        explanation = (
            f"{self.method} of {len(results)} models. {members_desc}. "
            f"Weighted point forecast {prediction:.4g}, pooled 95% interval "
            f"[{lower:.4g}, {upper:.4g}]."
        )

        return ForecastResult(
            model_name=self.name,
            method=self.method,
            version=self.version,
            target=ctx.target,
            horizon=ctx.horizon,
            prediction=prediction,
            lower=lower,
            upper=upper,
            confidence=confidence,
            explanation=explanation,
            used_models=[r.model_name for r in results],
        )
