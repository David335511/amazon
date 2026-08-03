"""Core abstractions for the forecasting platform.

A `ForecastModel` is the unit of forecasting. It declares a name, a
human-readable method, a semantic version, a family (statistical / ml / llm /
ensemble) and which `ForecastTarget`s it supports. Its ``forecast`` method
turns a `ForecastContext` (historical series + optional features/metadata) into
a `ForecastResult` carrying a point prediction, a 95% confidence interval, a
confidence score, an explanation and — for ensembles — the member models used.

Because the platform is modular, **adding a forecasting model is just
subclassing `ForecastModel`** and registering it. Statistical models run on the
standard library; ML and LLM models are opt-in providers behind the same
interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from statistics import pstdev
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.forecasting.config import ForecastConfig

Z95 = 1.96


class ForecastTarget(StrEnum):
    """What is being forecast. Each target is represented as a numeric series."""

    PRICE = "price"
    ROI = "roi"
    PROFIT = "profit"
    INVENTORY = "inventory"
    SALES = "sales"
    BUY_BOX = "buy_box"  # probability of winning / holding the Buy Box (0..1)
    COMPETITION = "competition"  # competitive intensity or competitor count


class ForecastContext(BaseModel):
    """Everything a model needs to produce a forecast.

    ``series`` is the chronological history for the target (numbers).
    ``features`` are exogenous numeric inputs; ``metadata`` carries qualitative
    context (e.g. ``promotion_expected``, ``season_period``) that models like
    LLM reasoning consume.
    """

    target: ForecastTarget
    entity_type: str
    entity_id: str
    horizon: int = Field(ge=1)  # number of future periods to look ahead
    series: list[float] = Field(min_length=1)
    frequency: str | None = None  # daily | weekly | monthly | ...
    features: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)


class ForecastResult(BaseModel):
    """The output of a `ForecastModel.forecast`.

    Includes the point ``prediction``, a 95% ``confidence interval``
    (``lower``/``upper``), a ``confidence`` score, a human-readable
    ``explanation`` and — for ensembles — the ``used_models``.
    """

    model_name: str
    method: str
    version: str
    target: ForecastTarget
    horizon: int
    prediction: float
    lower: float
    upper: float
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    used_models: list[str] = Field(default_factory=list)
    # Historical accuracy of this model on this target (filled by the manager
    # from recorded actuals; empty until the first actual is recorded).
    historical_accuracy: dict[str, Any] = Field(default_factory=dict)


class ForecastModel(ABC):
    """Base class for all forecasting models.

    Subclasses override the class metadata and implement ``forecast``. They are
    discovered by the registry; `available` lets a deployment opt models out
    (e.g. ML models when sklearn is not installed).
    """

    name: ClassVar[str] = ""
    method: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    family: ClassVar[str] = "statistical"  # statistical | ml | llm | ensemble
    supports: ClassVar[tuple[ForecastTarget, ...]] = tuple(ForecastTarget)

    @classmethod
    def available(cls, _config: ForecastConfig) -> bool:
        """Whether this model can run in the given deployment."""
        return True

    @abstractmethod
    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        """Produce a forecast for the given context."""


# ──────────────────────────────────────────────────────────────
# Shared numeric helpers (standard library only)
# ──────────────────────────────────────────────────────────────


def series_mean(xs: list[float]) -> float:
    """Arithmetic mean of a series."""
    return sum(xs) / len(xs)


def series_std(xs: list[float]) -> float:
    """Population standard deviation (0.0 for fewer than two samples)."""
    if len(xs) < 2:
        return 0.0
    try:
        return pstdev(xs)
    except Exception:
        return 0.0


def clamp01(value: float) -> float:
    """Clamp a confidence into [0.05, 1.0] (never zero, never over one)."""
    return max(0.05, min(1.0, value))


def forecast_interval(prediction: float, std: float) -> tuple[float, float]:
    """95% confidence interval around a prediction given a std deviation."""
    return prediction - Z95 * std, prediction + Z95 * std


def trend_slope(series: list[float]) -> float:
    """OLS slope of the series vs its index (for trend-aware reasoning)."""
    n = len(series)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = series_mean(series)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if not denom:
        return 0.0
    return sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, series, strict=True)
    ) / denom
