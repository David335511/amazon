# Forecasting Platform

Predict future **price, ROI, profit, inventory, sales, Buy Box ownership, and
competition** from historical series. Every forecast returns:

- a **prediction** (point value)
- a **confidence interval** (95% upper/lower)
- an **explanation** (human-readable, method + inputs)
- **historical accuracy** (the model's actual MAE / MAPE / RMSE / bias on that
  target from recorded outcomes)

Everything is **modular**: each forecasting method is a `ForecastModel` behind a
single interface, discovered by a registry. Plugging in a new model is defining
one subclass and registering it.

Built on the same conventions as the features, documents, vision and memory
subsystems (FastAPI + PostgreSQL + alembic + DI).

---

## Model families

| Family | Models | Notes |
|---|---|---|
| **Statistical** (pure stdlib) | moving average, exponential smoothing, linear trend, seasonal average, persistence | Always available, deterministic, explainable |
| **Machine learning** | linear regression, gradient boosting (lagged features) | Requires `pip install '.[forecasting]'` (scikit-learn). Auto-opt-out when sklearn is absent |
| **LLM reasoning** | `llm_reasoning` | Deterministic reasoning narrative over stats/trend/volatility/context; a seam for real providers |
| **Ensemble** | `ensemble` | Inverse-variance weighted combination of all available members |

Each model runs on the same numeric series regardless of target, so every model
supports every target (Buy Box is treated as the probability of winning /
holding the Buy Box; competition as competitive intensity or competitor count).

---

## Plugging in a new forecasting model

A model is just a `ForecastModel` subclass:

```python
from app.forecasting.base import ForecastContext, ForecastModel, ForecastResult

class MyModel(ForecastModel):
    name = "my_model"
    method = "Some technique"
    version = "1.0.0"
    family = "statistical"          # statistical | ml | llm | ensemble

    @classmethod
    def available(cls, config):     # optional opt-out
        return True

    def forecast(self, ctx: ForecastContext) -> ForecastResult:
        prediction = ...            # from ctx.series, ctx.features, ctx.metadata
        lower, upper = ...          # 95% confidence interval
        return ForecastResult(
            model_name=self.name, method=self.method, version=self.version,
            target=ctx.target, horizon=ctx.horizon,
            prediction=prediction, lower=lower, upper=upper,
            confidence=0.8, explanation="...",
        )
```

Then import it in `app/forecasting/registry.py` and add it to `_member_classes()`.
The registry, the ensemble and the API pick it up automatically. If it should
not run in some deployment, override `available()`.

---

## API

All routes under `/api/v1/forecasting` (API-key auth when Phase 0 security is on).

| Endpoint | Method | Purpose |
|---|---|---|
| `/forecasting/forecast` | POST | forecast a target for an entity; returns + stores the result |
| `/forecasting/batch` | POST | forecast many entities/targets in one call (bounded) |
| `/forecasting/forecasts` | GET | list stored forecasts (filter by target / entity / model) |
| `/forecasting/forecasts/{id}` | GET | a stored forecast with its historical accuracy |
| `/forecasting/forecasts/{id}/actual` | POST | record the realized outcome for that forecast |
| `/forecasting/actuals` | POST | record a realized outcome by `forecast_id` or target+entity |
| `/forecasting/accuracy` | GET | historical accuracy (MAE / MAPE / RMSE / bias) per model & target |
| `/forecasting/models` | GET | registered models (method, version, family, supported targets) |
| `/forecasting/capabilities` | GET | targets + models + default model + max horizon |
| `/forecasting/stats` | GET | store statistics |

### Forecast

```json
POST /api/v1/forecasting/forecast
{
  "target": "price",
  "entity_type": "product",
  "entity_id": "B0TEST001",
  "horizon": 1,
  "series": [10.1, 10.4, 10.3, 10.8, 11.0],
  "frequency": "weekly",
  "features": {"competitor_price": 9.9},
  "metadata": {"promotion_expected": "true"},
  "model": "ensemble"
}
```

- `model` may name a specific model (e.g. `"linear_trend"`, `"llm_reasoning"`)
  or be omitted to use the configured default (`ensemble`).
- `metadata` carries qualitative context consumed by reasoning models (e.g.
  `promotion_expected`, `supply_disruption`, `season_period`, `alpha`,
  `window`).

### Response

```json
{
  "id": "…",
  "target": "price",
  "entity_type": "product",
  "entity_id": "B0TEST001",
  "horizon": 1,
  "model_name": "ensemble",
  "method": "Inverse-variance weighted combination of member models",
  "version": "1.0.0",
  "prediction": 10.74,
  "lower": 9.91,
  "upper": 11.57,
  "confidence": 0.82,
  "explanation": "Inverse-variance weighted combination of 6 models. …",
  "used_models": ["moving_average", "exponential_smoothing", "linear_trend", "seasonal_average", "persistence", "llm_reasoning"],
  "historical_accuracy": {"model_name": "ensemble", "target": "price", "sample_count": 24, "mae": 0.31, "mape": 0.028, "rmse": 0.39, "bias": -0.02},
  "series": [10.1, 10.4, 10.3, 10.8, 11.0],
  "created_at": "2026-08-04T10:00:00Z"
}
```

### Recording actuals → historical accuracy

To score a model, record what actually happened at the forecasted period:

```json
POST /api/v1/forecasting/forecasts/{forecast_id}/actual
{ "actual_value": 10.6 }
```

or, by entity (links to that entity's latest forecast for the target):

```json
POST /api/v1/forecasting/actuals
{ "target": "price", "entity_type": "product", "entity_id": "B0TEST001", "actual_value": 10.6 }
```

Every recorded actual is matched to its forecast, and accuracy is recomputed on
demand — MAE (mean absolute error), MAPE (%), RMSE and bias (signed). This
**historical accuracy is returned on every forecast** so you always see how each
model has actually been performing, not just how it claims to perform.

---

## Storage

Two tables (Alembic migration `0008`, new head):

- **`forecasts`** — one row per forecast with the full result (prediction,
  interval, confidence, model name/method/version, ensemble members,
  explanation) **plus a snapshot of the input series / features / metadata**
  for reproducibility and audit.
- **`forecast_actuals`** — realized outcomes linked to a forecast (cascade on
  delete), the raw material for accuracy scoring.

---

## Configuration (`forecasting:` block in `config/<env>.yaml`)

```yaml
forecasting:
  enabled: true
  default_model: ensemble      # or any registered model name
  max_horizon: 36              # max look-ahead per request
  max_batch_size: 50           # batch guardrail
  enable_ml: true              # sklearn models only if installed too
  enable_llm: true             # LLM reasoning on/off
  llm_provider: reasoning      # reasoning | (future) openai|anthropic
  ensemble_members:            # subset of registered models used by the ensemble
    - moving_average
    - exponential_smoothing
    - linear_trend
    - seasonal_average
    - persistence
    - llm_reasoning
```

DI wiring in `app/core/dependencies.py` (`get_forecasting_manager`); router
`app/api/v1/forecasting.py`; migration `alembic/versions/0008_create_forecast_tables.py`.

---

## Design notes & production guidance

- **Confidence intervals widen with uncertainty.** Statistical models derive the
  interval from residual / rolling variance; the LLM-reasoning model scales it
  by √horizon (compounding uncertainty over longer look-aheads); the ensemble
  pools member variances. Never treat the point value without the interval.
- **`persistence` (no-change) is the baseline to beat.** It is frequently the
  strongest naive model; the ensemble includes it so its strength is captured.
- **Accuracy is earned, not claimed.** A brand-new model reports
  `sample_count: 0` until real outcomes are recorded. Feed actuals regularly
  (a nightly job that records last period's realized values is ideal) and watch
  per-model MAE/MAPE to decide which models to trust per target.
- **ML is additive.** Install `scikit-learn` (`pip install '.[forecasting]'`)
  and the ML models register automatically alongside the statistical ones.
  Their `version` is the model version.
- **LLM seam.** `llm_reasoning` is deterministic so forecasting works offline and
  is fully testable; a real provider (OpenAI / Anthropic) can be wired behind
  the same `ForecastModel.forecast` without changing the API or the store.
- **Future**: chain forecasts into the feature store (a forecast is itself a
  feature input), trigger `record_actual` off the event bus when prices/sales
  land, and let the ensemble weights be learned from historical accuracy.
