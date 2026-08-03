# Supplier Intelligence

Tracks the **historical** behaviour of suppliers and computes **five scores**
purely from that history, plus an **AI explanation** of supplier behaviour.

> **Everything is historical.** A supplier is never judged on a live snapshot —
> only on its accumulated record over time. Each `SupplierObservation` is one
> period snapshot, and every score is recomputed on demand over the full stored
> series, so it never goes stale and always reflects everything we know.

---

## What it tracks (per observation period)

| Tracked dimension | Column |
|---|---|
| **Historical prices** | `price` (+ `discount_events`) |
| **Sale frequency** | `sale_events` |
| **Coupon frequency** | `coupon_events` |
| **Inventory stability** | `inventory_level`, `inventory_variance` |
| **Shipping speed** | `shipping_days` |
| **Return policy** | `return_policy_score` (0..1 leniency) |
| **Customer service** | `customer_service_score` (0..1 quality) |
| **Order cancellation rate** | `order_cancellation_rate` (0..1) |
| **Discount patterns** | `discount_depth` (0..1), `discount_events` |
| **Stockout frequency** | `stockouts` |

Each row is tagged with `supplier_id`, `supplier_name`, `observed_at` (end of
the period) and `source` (e.g. `plugin`, `manual`, `sync`) so you can see where
the history came from.

---

## Scores computed (all 0..1, with confidence + component breakdown)

| Score | What it means |
|---|---|
| **Supplier Reliability Score** | How dependable the supplier is — fast shipping, stable inventory, low stockouts / cancellations, good service & returns. |
| **Supplier Volatility Score** | How unstable its behaviour is (price / inventory / shipping swings, stockout swings). *Higher = worse.* |
| **Supplier Discount Score** | How favourable its discounting is — depth, coupon frequency, sale frequency. |
| **Supplier Risk Score** | Overall downside — volatility, stockouts, cancellations, slow shipping, weak service / returns. *Higher = worse.* |
| **Supplier Seasonality Score** | How seasonal / periodic its pricing is (measured by how much of the price-series variance is explained by a recurring phase). |

Every score returns `value`, `confidence` (grows with `min_samples`
observations) and a `components` breakdown so you can see *why*.

### Example
```json
{
  "reliability": { "value": 0.92, "confidence": 1.0, "components": {
      "shipping": 0.79, "inventory": 1.0, "stockout": 1.0,
      "cancellation": 0.99, "customer_service": 0.9, "return_policy": 0.8 } },
  "volatility":  { "value": 0.05, "confidence": 1.0, "components": { ... } },
  "discount":    { "value": 0.03, "confidence": 1.0, "components": { ... } },
  "risk":        { "value": 0.06, "confidence": 1.0, "components": { ... } },
  "seasonality": { "value": 0.00, "confidence": 1.0, "components": { "best_period": null, "explained_variance": 0.0 } }
}
```

---

## AI explanation of supplier behaviour

Each profile includes an `explanation` — a deterministic reasoning narrative
that reads like an analyst summary and blends the scores with the metric
history:

> *"Based on 10 historical period(s), this supplier is highly reliable (0.92) —
> dependable shipping, stable inventory and low cancellations. Behaviour is
> stable across periods (volatility 0.05). Discount activity is light (0.03);
> pricing stays firm. Overall risk is low (0.06). No strong seasonality
> detected (strength 0.00); demand looks steady year-round."*

The provider is pluggable behind `explanation_provider` (default `reasoning`,
deterministic + zero external calls). A real LLM provider can synthesize the
same inputs behind the same interface.

---

## API

All routes under `/api/v1/supplier-intel` (API-key auth when security is on).

| Endpoint | Method | Purpose |
|---|---|---|
| `/supplier-intel/observations` | POST | record one historical period snapshot (201) |
| `/supplier-intel/observations` | GET | list history (filter by `supplier_id`, paginate) |
| `/supplier-intel/observations/{id}` | GET | a single observation |
| `/supplier-intel/scores` | GET | the five scores (`?supplier_id=`) |
| `/supplier-intel/profile` | GET | metrics + scores + explanation |
| `/supplier-intel/profile/batch` | POST | profile many suppliers (skips those with no history) |
| `/supplier-intel/explain` | GET | just the AI explanation |
| `/supplier-intel/suppliers` | GET | distinct suppliers with history |
| `/supplier-intel/capabilities` | GET | scores + tracked metrics available |
| `/supplier-intel/stats` | GET | totals and per-supplier counts |

### Record an observation
```json
POST /api/v1/supplier-intel/observations
{
  "supplier_id": "walmart",
  "supplier_name": "Walmart",
  "observed_at": "2026-08-05T00:00:00Z",
  "price": 12.5,
  "sale_events": 1,
  "coupon_events": 0,
  "inventory_level": 100,
  "inventory_variance": 1.0,
  "stockouts": 0,
  "shipping_days": 4,
  "return_policy_score": 0.8,
  "customer_service_score": 0.9,
  "order_cancellation_rate": 0.01,
  "discount_depth": 0.05,
  "discount_events": 0,
  "source": "plugin"
}
```

### Get a profile
```json
GET /api/v1/supplier-intel/profile?supplier_id=walmart
```

---

## Storage

One table, `supplier_observations` (Alembic migration `0010`, new head). Scores
are **computed on demand** from this history — never cached as stale aggregates.

---

## Configuration (`supplier_intel:` block in `config/<env>.yaml`)

```yaml
supplier_intel:
  enabled: true
  max_shipping_days: 14.0      # shipping at/above this scores zero on shipping reliability
  volatility_scale: 0.5        # coefficient-of-variation considered "high"
  max_coupon_rate: 5.0         # coupons per period at full credit
  max_sale_rate: 5.0           # sale events per period at full credit
  max_stockout_rate: 3.0       # stockouts per period at no credit
  min_samples: 8               # observations needed for full score confidence
  max_batch_size: 50
  explanation_provider: reasoning
```

DI wiring in `app/core/dependencies.py` (`get_supplier_intel_manager`); router
`app/api/v1/supplier_intel.py`; migration
`alembic/versions/0010_create_supplier_observation_tables.py`.

---

## Design notes & production guidance

- **Pure, testable math.** All formulas live in `app/supplier_intel/scoring.py`
  (`compute_scores`, `summarize`, `explain`) as deterministic, stdlib-only
  functions. The manager only wires them to the store.
- **Feed it over time.** Connect a supplier plugin (`app/plugins/`) or a
  scheduled sync to `POST /observations` each period. Reliability is only as
  good as the history — score confidence rises toward 1.0 as you reach
  `min_samples` snapshots.
- **Compose with the other engines.** Use **forecasting** to project a
  supplier's future price from its historical `price` series; feed the
  **feature store** with these scores (reliability / risk / volatility are
  natural features); let the **event bus** drive observations when supplier
  data lands.
- **Use risk + volatility for sourcing.** A high Reliability with low Volatility
  and low Risk is a preferred supplier; a high Discount score is a margin
  opportunity. The agent / sourcing pipeline can gate decisions on these.
- **`explanation_provider` is a seam.** Swap the deterministic narrative for a
  real LLM without touching the scoring or storage.
