# Experimentation Platform

A reproducible experimentation platform for A/B tests, feature flags, prompt /
rule testing, and scoring / LLM / supplier / prediction comparisons. It tracks
the **winner**, **confidence**, **profit impact**, **ROI impact**, **precision**,
**recall**, **false positives** and **false negatives**, and generates
**experiment reports**.

Everything is **reproducible**: the same observations always produce the same
winner, confidence, impact and report — across process restarts and deploys.

## Supported experiment types

| Type                  | Default metric | What it compares                                   |
|-----------------------|----------------|----------------------------------------------------|
| `ab_test`             | conversion     | Two (or more) variants' conversion rate            |
| `feature_flag`        | conversion     | Feature on/off vs control                          |
| `prompt`              | conversion     | Prompt variants on an outcome metric               |
| `rule`                | conversion     | Decision-rule variants on an outcome metric        |
| `scoring_comparison`  | precision      | Scoring functions on precision/recall              |
| `llm_comparison`      | accuracy       | Models / prompts on accuracy                       |
| `supplier_comparison` | profit         | Suppliers on profit / ROI                          |
| `prediction_comparison`| precision     | Prediction methods on precision/recall/FP/FN       |

## What it tracks

- **Winner** — the variant that beats the control significantly, plus the
  `leading` variant when nothing is significant yet.
- **Confidence** — `1 - p_value` of the significance test vs the control.
- **Profit impact** — winner mean profit minus control mean profit.
- **ROI impact** — winner mean ROI minus control mean ROI.
- **Precision / recall / false positives / false negatives** — confusion metrics
  per variant (for prediction / scoring / LLM comparisons, from `predicted` vs
  `ground_truth` labels).

## How winners are decided (pure statistics)

The engine (`app/experiments/engine.py`) is **standard-library only** and fully
deterministic:

- **Binary metrics** (conversion, accuracy, precision, recall) — two-proportion
  **z-test** between each variant and the control.
- **Continuous metrics** (profit, ROI, value) — **Welch's t-test** using an
  exact Student's-t CDF via the regularized incomplete beta function (accurate
  for small samples).
- A variant wins when it is **better** than the control **and** `p < alpha`
  (default `0.05`).
- **Sample-size planning** (`required_sample_size`) and a **reproducible A/B
  simulator** (`POST /experiments/simulate`) help size tests before launch.

## Reproducibility guarantees

1. **Deterministic assignment** — a subject maps to a variant via a stable
   SHA-256 of `"{seed}:{subject}"`, *not* Python's process-randomized `hash()`.
   The same subject under the same seed lands on the same variant **even after a
   service restart or deploy**.
2. **Pure statistics** — results are functions only of the stored observations.
3. **Snapshot at start** — each experiment records its config + the
   deployment's `code_version` when started (`config_snapshot`).
4. **Snapshot per report** — every report stores its full `params_snapshot`
   (config, variants, code version, observation count, seed).
5. **Unique per subject** — one assignment and one observation per
   (experiment, subject), so replaying a subject stream never doubles data
   (enforced by DB unique constraints too).

## API

Lifecycle:

| Method | Path                              | Purpose                                    |
|--------|-----------------------------------|--------------------------------------------|
| GET    | `/api/v1/experiments/capabilities`| Supported types / metrics / tracking       |
| GET    | `/api/v1/experiments/templates`   | Bundled experiment templates               |
| GET    | `/api/v1/experiments/stats`       | Platform-wide aggregation                  |
| POST   | `/api/v1/experiments/simulate`    | Reproducible A/B planning simulation       |
| POST   | `/api/v1/experiments`             | Create an experiment (draft) + variants    |
| GET    | `/api/v1/experiments`             | List experiments (filter by type/status)   |
| GET    | `/api/v1/experiments/{id}`        | Detail + variants + live results           |
| PATCH  | `/api/v1/experiments/{id}`        | Update a draft experiment                  |
| DELETE | `/api/v1/experiments/{id}`        | Delete (cascades children)                 |
| POST   | `/api/v1/experiments/{id}/variants`| Add a variant (draft only)                |
| POST   | `/api/v1/experiments/{id}/start`  | Start (snapshots config + code version)    |
| POST   | `/api/v1/experiments/{id}/stop`   | Stop + generate the final report           |

Data & analytics:

| Method | Path                                          | Purpose                                |
|--------|-----------------------------------------------|----------------------------------------|
| POST   | `/api/v1/experiments/{id}/assign`             | Deterministic subject assignment       |
| POST   | `/api/v1/experiments/{id}/observations`       | Record one outcome (auto-assigns)      |
| POST   | `/api/v1/experiments/{id}/observations/batch` | Record many outcomes (deduped)         |
| GET    | `/api/v1/experiments/{id}/observations`       | List observations                      |
| GET    | `/api/v1/experiments/{id}/results`            | Live per-variant stats + winner        |
| GET    | `/api/v1/experiments/{id}/winner`             | Current winner + confidence            |
| GET    | `/api/v1/experiments/{id}/precision-recall`   | Precision / recall / FP / FN per arm   |
| POST   | `/api/v1/experiments/{id}/report`             | Generate (and store) a report          |
| GET    | `/api/v1/experiments/{id}/report`             | Latest stored report                   |
| GET    | `/api/v1/experiments/{id}/reports`            | All stored reports (newest first)      |

### Example flow

```bash
# 1. create
curl -X POST .../api/v1/experiments \
  -H 'Content-Type: application/json' \
  -d '{"name":"Checkout AB","experiment_type":"ab_test",
       "variants":[{"key":"control","label":"Control","is_control":true},
                   {"key":"variant_a","label":"New","parameters":{"layout":"new"}}]}'

# 2. start
curl -X POST .../api/v1/experiments/<id>/start

# 3. assign + record
curl -X POST .../api/v1/experiments/<id>/assign -d '{"subject_key":"u1"}'
curl -X POST .../api/v1/experiments/<id>/observations \
  -d '{"subject_key":"u1","outcome":true,"profit":5.0}'

# 4. analyze
curl .../api/v1/experiments/<id>/results
curl .../api/v1/experiments/<id>/winner

# 5. report
curl -X POST .../api/v1/experiments/<id>/report
```

## Storage

- `experiments` — lifecycle, statistical config, seed, config/code snapshot.
- `experiment_variants` — arms of an experiment (key, label, parameters).
- `experiment_assignments` — deterministic subject → variant (unique per
  experiment + subject).
- `experiment_observations` — one outcome per subject (conversion, profit, ROI,
  value, predicted vs ground truth).
- `experiment_reports` — every generated report (winner, confidence, impact,
  quality, params snapshot).

All child tables cascade on experiment delete.
