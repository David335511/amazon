"""Machine-learning forecasting models.

These models learn a supervised lag-based regressor from the historical series
and forecast recursively. They require ``scikit-learn`` — installed via
``pip install '.[forecasting]'``. If sklearn is not installed (or ML is
disabled in config), `available()` returns False and the models are simply not
registered, so statistical / LLM / ensemble forecasting still work.

The plug-in seam is identical to the statistical models: subclass
`ForecastModel`, declare metadata, implement ``forecast``.
"""

from __future__ import annotations

from typing import Any

from app.forecasting.base import (
    ForecastContext,
    ForecastModel,
    ForecastResult,
    clamp01,
    forecast_interval,
    series_std,
)


def _lag_dataset(series: list[float], lag: int) -> tuple[list[list[float]], list[float]]:
    """Build (X, y) supervised pairs where y[t] is predicted from the prior `lag` values."""
    xs: list[list[float]] = []
    ys: list[float] = []
    for t in range(lag, len(series)):
        xs.append(series[t - lag : t])
        ys.append(series[t])
    return xs, ys


def _lag_forecast(reg_factory: Any, series: list[float], horizon: int, lag: int) -> tuple[float, float]:
    """Fit a regressor on lag features and forecast recursively.

    Returns (point_prediction, residual_std).
    """
    if len(series) < lag + 1:
        lag = max(1, len(series) - 1)
    xs, ys = _lag_dataset(series, lag)
    if not xs:
        return series[-1], series_std(series) or abs(series[-1]) * 0.1

    reg = reg_factory()
    reg.fit(xs, ys)
    preds = []
    window = list(series[-lag:])
    for _ in range(horizon):
        x = [window[-lag:]]  # last `lag` known/forecast values
        nxt = float(reg.predict(x)[0])
        preds.append(nxt)
        window.append(nxt)

    residuals = [y - float(reg.predict([x])[0]) for x, y in zip(xs, ys, strict=True)]
    resid_std = series_std(residuals) or abs(preds[-1]) * 0.1
    return preds[-1], resid_std


class _BaseMLModel(ForecastModel):
    """Shared behaviour for sklearn-backed forecasting models."""

    family = "ml"

    @classmethod
    def available(cls, config) -> bool:
        if not config.enable_ml:
            return False
        try:
            import sklearn  # noqa: F401

            return True
        except ImportError:
            return False

    # Subclasses provide the sklearn regressor factory (imported lazily).
    def _regressor(self) -> Any:
        raise NotImplementedError

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        # Availability is enforced by the registry at build time.
        lag = _lag_from_metadata(ctx, 3)
        prediction, resid_std = _lag_forecast(self._regressor, ctx.series, ctx.horizon, lag)
        lower, upper = forecast_interval(prediction, resid_std)
        return ForecastResult(
            model_name=self.name,
            method=self.method,
            version=self.version,
            target=ctx.target,
            horizon=ctx.horizon,
            prediction=prediction,
            lower=lower,
            upper=upper,
            confidence=clamp01(1.0 - (resid_std / max(abs(prediction), 1e-9))),
            explanation=(
                f"{self.method}. Lag features={lag}, trained on {len(ctx.series)} "
                f"observations, point={prediction:.4g}."
            ),
        )


class SklearnLinearModel(_BaseMLModel):
    """Linear regression over lag features (scikit-learn)."""

    name = "ml_linear_regression"
    method = "Scikit-learn linear regression on lagged features (recursive forecast)"
    version = "1.0.0"

    def _regressor(self) -> Any:
        from sklearn.linear_model import LinearRegression

        return LinearRegression


class SklearnGradientBoostingModel(_BaseMLModel):
    """Gradient boosting over lag features (scikit-learn)."""

    name = "ml_gradient_boosting"
    method = "Scikit-learn GradientBoostingRegressor on lagged features"
    version = "1.0.0"

    def _regressor(self) -> Any:
        from sklearn.ensemble import GradientBoostingRegressor

        return GradientBoostingRegressor


def _lag_from_metadata(ctx: ForecastContext, default: int) -> int:
    raw = ctx.metadata.get("lag")
    if raw and raw.isdigit():
        return max(1, int(raw))
    return default
