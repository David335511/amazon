"""Forecasting model registry — plugging in new models.

`build_models(config)` instantiates every *available* model (statistical models
always; ML models only when sklearn is installed and ML is enabled; LLM
reasoning when LLM is enabled) plus the `ensemble` that combines them. Returns
``{name: ForecastModel}``.

**Adding a model is a one-liner**: define a `ForecastModel` subclass, import it
here, and add it to the ``_BASE_CLASSES`` list. The registry and ensemble pick
it up automatically; `available()` lets a deployment opt it out.
"""

from __future__ import annotations

from app.forecasting.base import ForecastConfig, ForecastModel
from app.forecasting.ensemble import EnsembleModel
from app.forecasting.llm import LLMReasoningModel
from app.forecasting.machine_learning import (
    SklearnGradientBoostingModel,
    SklearnLinearModel,
)
from app.forecasting.statistical import (
    ExponentialSmoothingModel,
    LinearTrendModel,
    MovingAverageModel,
    PersistenceModel,
    SeasonalAverageModel,
)


def _member_classes() -> list[type[ForecastModel]]:
    """All non-ensemble model classes available to a deployment."""
    return [
        MovingAverageModel,
        ExponentialSmoothingModel,
        LinearTrendModel,
        SeasonalAverageModel,
        PersistenceModel,
        SklearnLinearModel,
        SklearnGradientBoostingModel,
        LLMReasoningModel,
    ]


def build_models(config: ForecastConfig) -> dict[str, ForecastModel]:
    """Return ``{model_name: ForecastModel}`` for available models + ensemble."""
    members: list[ForecastModel] = []
    for cls in _member_classes():
        if cls.available(config):
            members.append(cls())

    models: dict[str, ForecastModel] = {m.name: m for m in members}

    # Ensemble combines the non-ensemble members. An explicit member subset in
    # config is honoured when it references registered models.
    subset = [m for m in members if m.name in config.ensemble_members] or members
    models["ensemble"] = EnsembleModel(subset)
    return models
