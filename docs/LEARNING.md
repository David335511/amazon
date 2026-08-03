# Continuous-Learning Platform

A self-improving feedback loop for the commerce platform. It records every
prediction (profit, sales, ROI, risk) with its model version and a feature
snapshot, feeds the real outcomes back, measures accuracy over time, **automatically
detects what's going wrong**, and **generates actionable improvement
recommendations** — prompts, feature weights, matching algorithms, forecast
models and rule thresholds — then **deterministically auto-tunes** the ones it can
(rule thresholds, feature weights). Everything is **versioned, explainable and
reproducible**.

## The feedback loop

```
 record prediction ──► outcome arrives ──► resolved prediction
      (model_version,                          │
       decision context,                       ▼
       feature snapshot)           compare predicted vs actual
                                        (profit / sales / ROI / risk)
                                           │
                      ┌────────────────────┴───────────────────┐
                      ▼                                        ▼
         accuracy over time                         automatic issue scan
         (MAE / RMSE / MAPE / bias /                (bad rules, weak prompts,
          directional / correlation)                 poor decisions, bad matches,
                      │                              ranking mistakes)
                      ▼                                        ▼
                dashboard                              improvement recommendations
                                                   (prompt / feature weight /
                                                      matching / forecast / rule)
                                                            │
                                                            ▼
                                                 deterministic auto-tuning
                                               (rule threshold grid search,
                                                feature re-weighting)
```

## Predicted vs actual (the four comparisons)

Every resolved outcome contributes to a comparison per metric:

| Metric | What's compared |
|--------|-----------------|
| **profit** | predicted net profit vs actual |
| **sales** | predicted units/revenue vs actual |
| **ROI** | predicted ROI vs actual |
| **risk** | predicted risk score vs actual |

`GET /learning/comparison` returns each metric's sample size, predicted/actual
means, MAE, bias, correlation and directional accuracy. `GET /learning/accuracy?prediction_type=profit`
adds the full summary plus the **rolling accuracy-over-time series**.

## Automatic issue identification

`POST /learning/scan/issues` groups resolved outcomes by (decision type, decision
id) and flags groups that clear a severity threshold (normalised MAE + missed
directional accuracy):

| Decision type | Detected issue | Example |
|---------------|----------------|---------|
| `rule` | **bad_rule** | a sourcing rule that consistently over-predicts |
| `prompt` | **weak_prompt** | a prompt that drifts on an outcome |
| `ai_decision` | **poor_decision** | a model decision that degrades accuracy |
| `match` | **incorrect_match** | a matcher that returns wrong products/suppliers |
| `ranking` | **ranking_mistake** | a ranker that orders the wrong entity first |

Each issue carries the offending decision id, model version, sample size, the
measured error, the mode (`over-prediction` / `under-prediction` /
`degraded accuracy`) and a severity score.

## Improvement recommendations

`POST /learning/cycle` (the versioned cycle) turns every detected issue into one
or more recommendations, choosing the right improvement target:

| Recommendation target | When generated | Proposed action |
|-----------------------|----------------|-----------------|
| **rule_threshold** | bad rule | tune the decision threshold to the optimum |
| **prompt** | weak prompt / poor decision | rewrite the prompt and A/B it |
| **matching_algorithm** | incorrect match / ranking mistake | retrain / re-parametrize the matcher, validate with a scoring experiment |
| **forecast_model** | profit/sales/ROI forecast drift | version-bump the forecast model and compare MAE |
| **feature_weight** | feature correlates with error | reweight the feature |

Every recommendation stores its **target, proposed action, severity, confidence,
current→proposed value, evidence and a human-readable explanation** — no black
box. Recommendations have a lifecycle: `open` → `applied` / `dismissed`
(`PATCH /learning/recommendations/{id}`).

## Continuous improvement without manual tuning

Two deterministic, data-driven tuners run inside each cycle:

- **Rule thresholds** — for rules with a `score` feature and binary outcomes, a
  grid search over the observed scores finds the threshold that maximises F1. If
  it meaningfully beats the current threshold, the new threshold is emitted as an
  **auto-applied** rule recommendation (`optimize_threshold` in the engine).
  `POST /learning/optimize/rule-threshold?decision_id=...` runs this on demand.
- **Feature weights** — for each feature that appears in resolved predictions, the
  platform correlates its values with the prediction error and proposes a reweight
  (positively-correlated features are down-weighted, negatively-correlated ones
  up-weighted). `POST /learning/reweight/feature` runs this on demand.

So the platform *becomes more accurate on its own*: as outcomes accumulate, it
keeps proposing better thresholds and weights and version-bumps the model that
produced them.

## Dashboard: model accuracy over time

`GET /learning/dashboard` returns:

- **overall** accuracy across all metrics,
- **by_metric** — per-metric summary,
- **models** — per-model-version accuracy (MAE, MAPE, bias, directional accuracy,
  severity), ranked worst-first so the most degraded models surface,
- **series** — the rolling accuracy-over-time series for each metric,
- open recommendations + last run number.

This is the "is the system getting better?" view.

## Versioning & explainability

- **Every prediction** carries a `model_version` and a `features_json` snapshot.
- **Every cycle run** is a `LearningRun` with a **monotonic run number**, a config
  + code-version snapshot, and a summary of what was measured, flagged, tuned and
  recommended — so you can reproduce any result exactly and see what changed
  between run 1 and run N.
- **All statistics are pure functions** of the stored outcomes (`app/learning/engine.py`):
  the same data always reproduces the same metrics, issues, thresholds and
  reweights. No hidden state, no randomness.
- Ingestion is **idempotent** via an optional `external_id`, so replaying a stream
  never duplicates predictions.

## API surface

| Endpoint | Purpose |
|----------|---------|
| `GET /learning/capabilities` | supported prediction/decision types, targets, metrics |
| `POST /learning/predictions` | record a prediction (idempotent via `external_id`) |
| `POST /learning/outcomes` | feed back a realised outcome (by subject/decision or external_id) |
| `GET /learning/predictions` | list (filter by type / decision / model / resolved) |
| `GET /learning/comparison` | predicted vs actual per metric |
| `GET /learning/accuracy` | summary + rolling series for a metric/model |
| `GET /learning/dashboard` | accuracy-over-time dashboard |
| `POST /learning/scan/issues` | detect issues (no persistence) |
| `POST /learning/optimize/rule-threshold` | tune a rule threshold |
| `POST /learning/reweight/feature` | suggest a feature reweight |
| `POST /learning/cycle` | run + persist a versioned learning cycle |
| `GET /learning/runs`, `GET /learning/runs/{id}` | versioned runs |
| `GET /learning/recommendations` | list recommendations |
| `PATCH /learning/recommendations/{id}` | apply / dismiss |
| `POST /learning/report` | markdown continuous-learning report |
| `GET /learning/stats` | platform aggregates |

## Quick start

```bash
# Record a profit prediction
curl -X POST .../api/v1/learning/predictions \
  -H 'Content-Type: application/json' \
  -d '{"prediction_type":"profit","subject_key":"ASIN-ERG01",
       "decision_type":"rule","decision_id":"price-rule-v1",
       "model_version":"1.0.0","predicted_value":42.0,
       "features":[{"name":"demand","value":3.2,"weight":0.4}]}'

# Feed back the actual profit
curl -X POST .../api/v1/learning/outcomes \
  -H 'Content-Type: application/json' \
  -d '{"prediction_type":"profit","subject_key":"ASIN-ERG01",
       "decision_id":"price-rule-v1","actual_value":35.0}'

# Measure accuracy over time
curl ".../api/v1/learning/accuracy?prediction_type=profit"

# Automatically detect issues
curl -X POST .../api/v1/learning/scan/issues

# Run a versioned continuous-learning cycle (detect + recommend + auto-tune)
curl -X POST .../api/v1/learning/cycle

# Dashboard
curl .../api/v1/learning/dashboard

# Markdown report
curl -X POST .../api/v1/learning/report
```

## Production readiness

- Pure-stdlib engine (no ML runtime required), deterministic end-to-end.
- Postgres persistence: `learning_predictions`, `learning_runs`,
  `learning_recommendations` (migration `0015_learning`, single head).
- Idempotent ingestion, versioned runs, config + code-version snapshots.
- Recommendation lifecycle and evidence-based explanations.
- Integration seam: the platform is self-contained today, and other modules
  (forecasting, finance, multi-agent) can emit predictions via the same
  `/predictions` + `/outcomes` endpoints as they produce results — no engine change.
