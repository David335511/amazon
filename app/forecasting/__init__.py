"""Forecasting platform.

Predicts future price, ROI, profit, inventory, sales, Buy Box ownership and
competition from historical series. Every forecast returns a **prediction, a
confidence interval, an explanation, and historical accuracy**.

Support:
- **Statistical models** (pure stdlib): moving average, exponential smoothing,
  linear trend, seasonal average, persistence.
- **Machine learning** (scikit-learn, opt-in via ``[forecasting]``): linear
  regression and gradient boosting on lagged features.
- **LLM reasoning**: a deterministic reasoning narrative over series statistics,
  trend, volatility and qualitative context (a seam for real providers).
- **Ensemble**: inverse-variance weighted combination of the available models.

Modular by design: every model is a `ForecastModel` subclass behind the same
interface, discovered by the registry — adding a forecasting model is just
defining a subclass and registering it. Historical accuracy (MAE / MAPE / RMSE
/ bias) is computed from realized outcomes recorded against each forecast.
"""

from app.forecasting.base import (
    ForecastContext,
    ForecastModel,
    ForecastResult,
    ForecastTarget,
)
from app.forecasting.config import ForecastConfig
from app.forecasting.errors import (
    ForecastError,
    ForecastNotFoundError,
    ForecastUnavailableError,
    ForecastValidationError,
)
from app.forecasting.manager import ForecastingManager
from app.forecasting.models import Forecast, ForecastActual
from app.forecasting.registry import build_models
from app.forecasting.repository import ForecastingRepository
from app.forecasting.schemas import (
    AccuracyRead,
    ForecastActualRead,
    ForecastActualRequest,
    ForecastBatchItem,
    ForecastBatchRequest,
    ForecastingCapabilities,
    ForecastingStats,
    ForecastList,
    ForecastRead,
    ForecastRequest,
    ModelDefinition,
)

__all__ = [
    "AccuracyRead",
    "Forecast",
    "ForecastActual",
    "ForecastActualRead",
    "ForecastActualRequest",
    "ForecastBatchItem",
    "ForecastBatchRequest",
    "ForecastConfig",
    "ForecastContext",
    "ForecastError",
    "ForecastList",
    "ForecastModel",
    "ForecastNotFoundError",
    "ForecastRead",
    "ForecastRequest",
    "ForecastResult",
    "ForecastTarget",
    "ForecastUnavailableError",
    "ForecastValidationError",
    "ForecastingCapabilities",
    "ForecastingManager",
    "ForecastingRepository",
    "ForecastingStats",
    "ModelDefinition",
    "build_models",
]
