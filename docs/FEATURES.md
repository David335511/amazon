# Feature Engineering Platform

Compute engineered metrics **once**, store them, and **reuse** them — a feature
store for the Amazon AI Commerce Platform. Every value carries its **calculation
method, timestamp, confidence, version, and lineage**, so any downstream
decision (sourcing, pricing, buy-box, restocking) is reproducible and auditable.

Backed by FastAPI + PostgreSQL + the same DI / layered-config / migration
conventions as the vision, documents and memory subsystems.

---

## Why a feature store

Naively, every consumer (pricing, sourcing, agent) recomputes the same metrics
over and over. A feature store inverts that:

- **Compute once, reuse**: the latest value per `(feature, entity)` is
  persisted and served until it goes stale (`computed_at + ttl`), then
  recomputed.
- **Single source of truth**: one formula, one version, one stored value — no
  drift between consumers.
- **Provenance built in**: every value records *what* signals (with versions)
  and *which* method produced it.

```
POST /features/calculate   ->  store  ->  GET /features/value (reused until stale)
        |                                  ^
        v                                  |
   compute (if not fresh)  ---------------+
   + version + lineage
```

---

## The pipeline

```
request (feature, entity)
  → FeatureComputer declared formula (versioned)
  → SignalProvider fetches input signals
  → compute → {value, confidence, used_signals}
  → build lineage (method, version, inputs, output hash)
  → upsert into feature_values  (compute-once)
  → return FeatureValueRead
```

`FeatureManager` is the **only** entry point. Adding a feature (including a
future ML model) is just subclassing `FeatureComputer` — the registry
auto-discovers it.

---

## Feature catalog

Every feature declares its key, formula (method), semantic **version**, value
type, required signals, and refresh **TTL**. All are listed live via
`GET /api/v1/features/definitions`.

| Feature | Key | Formula (method) | Signals |
|---|---|---|---|
| **Price Stability Score** | `price_stability_score` | `1 - min(1, std/mean of price_history)` | `price_history` |
| **Brand Risk Score** | `brand_risk_score` | `clamp(0.05 + 0.2·indicators + 0.15·neg_reviews + 0.3·recall)` | `brand`, `brand_risk_indicators`, `negative_reviews_rate`, `recall_flag` |
| **Supplier Reliability** | `supplier_reliability_score` | `clamp(0.4·on_time + 0.3·fill + 0.3·(rating/5) − 0.1·incidents)` | `supplier_on_time_rate`, `supplier_fill_rate`, `supplier_rating`, `supplier_incidents` |
| **Competition Score** | `competition_score` | `clamp(0.3·min(1,n/10) + 0.7·price_pressure)` | `competitor_prices`, `list_price`, `buy_box_price` |
| **Buy Box Stability** | `buy_box_stability` | `clamp(0.5·share + 0.3·(1−vol) + 0.2·win_rate)` | `buy_box_share`, `price_volatility`, `win_rate` |
| **Inventory Health** | `inventory_health` | band scoring around `[reorder·1.5, max·0.8]` | `stock_level`, `reorder_point`, `max_stock`, `days_of_cover`, `turnover_rate` |
| **Velocity Score** | `velocity_score` | `clamp(0.5·(1 + (velocity − avg)/avg))` | `sales_velocity`, `category_avg_velocity` |
| **Seasonality Score** | `seasonality_score` | `1 − min(monthly)/max(monthly)` | `monthly_sales` |
| **Coupon Frequency** | `coupon_frequency` | `coupons · 30 / window_days` | `coupon_count`, `coupon_window_days` |
| **Restock Probability** | `restock_probability` | `1/(1+e^((stock−velocity·lead)/spread))` | `stock_level`, `sales_velocity`, `lead_time_days`, `reorder_point`, `demand_std` |
| **Expected Margin** | `expected_margin` | `(price − cost − price·fees − holding) / price` | `sell_price`, `cost`, `fees_pct`, `holding_cost` |
| **Expected ROI** | `expected_roi` | `expected_profit / invested_capital` | `expected_profit`, `invested_capital`, `roi` |
| **Expected Sales** | `expected_sales` | `velocity · seasonality · (1+growth) · (1+promo)` | `sales_velocity`, `seasonality_factor`, `demand_growth_rate`, `promotion_effect` |
| **Expected Turnover** | `expected_turnover` | `annual_sales / avg_inventory` | `annual_sales_qty`, `avg_inventory_qty` |

Each formula degrades gracefully when signals are missing: it returns a sensible
neutral/default value and **lowers confidence** (confidence = fraction of
required signals actually present, floored at 0.05). This is by design — a
feature is still usable with partial data, but its reliability is explicit.

---

## Every stored value carries provenance

A `FeatureValue` row records:

- **calculation method** — `lineage.method` (the human-readable formula)
- **timestamp** — `computed_at`
- **confidence** — `confidence` (0..1, from signal availability)
- **version** — `version` (semantic version of the computing function; bump on
  formula change)
- **lineage** — `lineage.inputs` (each signal with its `value`, `source` and
  `version`) plus an `output_hash` for auditability

```json
{
  "feature": "expected_margin",
  "method": "(sell_price - cost - sell_price*fees_pct - holding_cost) / sell_price",
  "version": "1.0.0",
  "computed_at": "2026-08-03T10:00:00+00:00",
  "output_hash": "9f2c1e7d0a3b8e4f",
  "inputs": [
    {"key": "sell_price", "value": 100, "source": "override", "version": "1.0.0"},
    {"key": "cost", "value": 60,  "source": "override", "version": "1.0.0"}
  ]
}
```

---

## API

All routes under `/api/v1/features` (API-key auth when Phase 0 security is on).

| Endpoint | Method | Purpose |
|---|---|---|
| `/features/calculate` | POST | compute (or return the stored fresh value) |
| `/features/refresh` | POST | force recompute and overwrite the stored value |
| `/features/value?feature_key=&entity_type=&entity_id=` | GET | retrieve the stored value (no recompute) |
| `/features/batch` | POST | compute many `{feature_key, entity_type, entity_id}` in one call |
| `/features/values` | GET | list stored values (filter by key/type/id) |
| `/features/definitions` | GET | every feature's method, version, value type, signals, TTL |
| `/features/definitions/{key}` | GET | one feature's definition |
| `/features/capabilities` | GET | features supported + signal provider |
| `/features/stats` | GET | store statistics (count per feature, stale count) |

### Calculate

```json
POST /api/v1/features/calculate
{
  "feature_key": "expected_margin",
  "entity_type": "product",
  "entity_id": "B0TEST001",
  "force": false,
  "signals": {"sell_price": 100, "cost": 60, "fees_pct": 0.15, "holding_cost": 5}
}
```

The `signals` field is an **override** merged over whatever the
`SignalProvider` returns — useful for what-if analysis and for callers that
already have the data in hand.

### Batch

```json
POST /api/v1/features/batch
{
  "requests": [
    {"feature_key": "velocity_score", "entity_type": "product", "entity_id": "B0TEST001"},
    {"feature_key": "expected_turnover", "entity_type": "product", "entity_id": "B0TEST001"}
  ],
  "force": false
}
```

---

## Storage

The `feature_values` table (Alembic migration `0007`) is the feature store:
one row per `(feature_key, entity_type, entity_id)` holding the *current* value
plus its audit trail. `value_json` is the canonical value (works for numeric,
categorical, boolean and vector features); `numeric_value` denormalizes numerics
so they can be ranged/aggregated in SQL.

```
feature_values
  feature_key, entity_type, entity_id   unique per entity
  value_type, value_json, numeric_value
  confidence, version, computed_at, stale_after
  lineage_json
```

---

## ML-readiness

- **`FeatureComputer` is the ML seam.** A trained model is registered the same
  way as any feature: a computer that reads model inputs from signals and emits
  a value + confidence. Its `version` doubles as the model version.
- **`SignalProvider` is the input seam.** Production integrations source
  signals from the platform's repositories (product, revenue, supplier) or a
  feature-server/HTTP service by implementing `SignalProvider`; ML training
  features are the same stored values consumed via `GET /features/values`.
- **Vector / categorical values** are supported via `FeatureValueType` — ready
  for embedding or one-hot style features.
- **Staleness drives retraining/refresh**: `stats.stale_values` and
  `stale_after` tell you which features need recomputation.

---

## Configuration (`feature_store:` block in `config/<env>.yaml`)

```yaml
feature_store:
  enabled: true
  default_ttl_seconds: 3600   # used when a feature has no ttl_seconds of its own
  signal_provider: local      # local | (future: db, http, feature-server)
  max_batch_size: 100         # batch guardrail
```

DI wiring in `app/core/dependencies.py` (`get_feature_manager`); router
`app/api/v1/features.py`; migration `alembic/versions/0007_create_feature_tables.py`.

---

## Production notes

- **Confidence is availability-based** (fraction of required signals present).
  For formula-inherent uncertainty, fold it into the signal set (e.g. a
  `demand_std`) — the confidence field already composes with it.
- **TTL is per-feature** (declared on the computer), with a config-level
  default as fallback. Tune refresh cadence per feature — cheap, stable
  features can have long TTLs; volatile ones short.
- **Bounded batch** prevents a single request from recomputing an unbounded
  number of features.
- **Future integrations**: the `SignalProvider` is the natural place to wire in
  the existing repositories, the event bus (recompute-on-signal), and the
  memory system (cache/store the lineage narratives).
