# Reverse Sourcing Engine

Turns an **Amazon ASIN** into a complete supplier analysis: every known
supplier that carries the product, their current & historical prices, shipping
costs, availability, discounts, a predicted future discount, a supplier
ranking with **best / cheapest / fastest / highest-confidence** picks, and
actionable sourcing recommendations.

It is **fully provider-driven and plug-in friendly** — adding a supplier is
just dropping a file in `app/plugins/suppliers/`; the engine never changes.

---

## What it outputs for one ASIN

| Output | Description |
|---|---|
| **Every known supplier** | all enabled supplier plugins that carry the product |
| **Historical supplier prices** | per-(supplier, ASIN) unit-price series from past runs |
| **Shipping costs** | cheapest available method cost + delivery days → landed cost |
| **Availability** | in-stock status + stock status per supplier |
| **Historical discounts** | per-(supplier, ASIN) discount-depth series from past runs |
| **Supplier ranking** | weighted score (price, speed, availability, discount, reliability, risk) |
| **Predicted future discount** | next-period discount depth per supplier (trend forecast) |
| **Best supplier** | highest ranked |
| **Cheapest supplier** | lowest landed cost |
| **Fastest supplier** | shortest delivery |
| **Highest-confidence supplier** | most historical data / highest supplier-intelligence confidence |
| **Sourcing recommendations** | actionable list + a summary paragraph |

---

## How it works

```
POST /api/v1/reverse-sourcing/source  {"asin": "B0TEST001", "quantity": 2}
  1. resolve ASIN -> product identity (UPC / title)   [AsinResolver]
  2. for each enabled supplier (SupplierProvider):
       find product by UPC/ASIN -> supplier SKU
       pricing -> unit price
       availability -> in stock / status
       shipping -> cheapest method (cost, days)
       coupon -> current discount depth
  3. historical prices & discounts (from past runs) for each supplier+ASIN
  4. predicted future discount per supplier           [DiscountPredictor]
  5. rank suppliers; pick best/cheapest/fastest/highest-confidence
  6. generate recommendations + summary
  7. persist the run + per-supplier offers
```

### Example response (abridged)
```json
{
  "asin": "B0TEST001",
  "offers": [
    { "supplier_code": "costco", "unit_price": 7.0, "shipping_cost": 7.99,
      "shipping_days": 7, "landed_cost": 14.99, "in_stock": true,
      "current_discount": 0.05, "predicted_discount": 0.1 },
    ...
  ],
  "historical": {
    "walmart": { "supplier_code": "walmart", "sample_count": 4,
                 "prices": [10.0, 10.0, 9.5, 10.0], "discounts": [0.1, 0.1, 0.15, 0.1] }
  },
  "ranking": [ { "supplier_code": "costco", "rank": 1, "score": 0.62, "components": {...} } ],
  "highlights": {
    "best": { "supplier_code": "costco", "reason": "highest ranked supplier", "landed_cost": 14.99 },
    "cheapest": { "supplier_code": "costco", ... },
    "fastest": { "supplier_code": "target", "shipping_days": 3, ... },
    "highest_confidence": { "supplier_code": "costco", ... }
  },
  "predicted_discounts": { "walmart": 0.1, "target": 0.0 },
  "recommendations": [
    "Buy from costco (costco): landed cost $14.99, ~7 day shipping.",
    "Walmart (walmart) is predicted ~10% off next period; consider timing the purchase."
  ],
  "summary": "Reverse sourcing for ASIN B0TEST001: evaluated 3 supplier(s). Recommended supplier is costco ..."
}
```

---

## Plug-in friendly (the key design)

The engine talks **only** to a `SupplierProvider` (`app/reverse_sourcing/provider.py`),
which adapts the existing `PluginManager`. `PluginManager` auto-discovers every
subclass of `BaseSupplierPlugin` in `app/plugins/suppliers/`.

> **To add a supplier:** add a `BaseSupplierPlugin` subclass file to
> `app/plugins/suppliers/` and enable it in config. **No engine change.**

Other pluggable seams:
- **`AsinResolver`** — default `PassthroughAsinResolver` (uses the ASIN + any
  UPC you send). Plug in a product-catalog / Keepa / Marketplace resolver to
  auto-derive UPC + title.
- **`DiscountPredictor`** — default `TrendDiscountPredictor` (pure-stdlib
  mean + trend). Plug in a forecasting model / LLM behind the same interface.
- **`SupplierProvider`** — default `PluginManagerProvider`. Swap in any
  implementation (e.g. a stub or a different source) without touching the engine.

---

## API

All routes under `/api/v1/reverse-sourcing` (API-key auth when security is on).

| Endpoint | Method | Purpose |
|---|---|---|
| `/reverse-sourcing/source` | POST | reverse-source an ASIN (201, returns + persists) |
| `/reverse-sourcing/runs` | GET | list stored runs (filter by `asin`, paginate) |
| `/reverse-sourcing/runs/{id}` | GET | a single stored run |
| `/reverse-sourcing/historical` | GET | historical price/discount series for a (supplier, ASIN) |
| `/reverse-sourcing/capabilities` | GET | enabled suppliers + features |
| `/reverse-sourcing/stats` | GET | totals and per-ASIN run counts |

---

## Storage

Two tables (Alembic migration `0011`, new head):

- **`reverse_sourcing_runs`** — one row per ASIN sourced (inputs + highlights + summary).
- **`reverse_sourcing_offers`** — one row per supplier per run (price, shipping,
  landed cost, availability, discount, rank, predicted discount). Accumulated
  across runs, these form the **historical** per-(supplier, ASIN) series.

Historical prices/discounts are derived by joining offers to their runs over
time — the more you reverse-source, the richer the history and the better the
discount forecasts and confidence.

---

## Configuration (`reverse_sourcing:` block in `config/<env>.yaml`)

```yaml
reverse_sourcing:
  enabled: true
  default_currency: USD
  default_quantity: 1
  max_suppliers: 50
  max_batch_size: 50
  forecast_horizon: 1
  # Ranking weights: price, speed, availability, discount, reliability, risk_inverse
  rank_weights: [0.30, 0.20, 0.15, 0.10, 0.15, 0.10]
```

DI wiring in `app/core/dependencies.py` (`get_reverse_sourcing_manager`); router
`app/api/v1/reverse_sourcing.py`; migration
`alembic/versions/0011_create_reverse_sourcing_tables.py`.

---

## Design notes & production guidance

- **Provider seam = plug-in point.** Because the engine never touches a plugin
  directly, onboarding a new marketplace is purely additive.
- **History is self-accumulating.** Run `source` on a schedule (or when
  supplier data lands) and the historical series + predicted discounts + high
  confidence grow automatically. Combine with **supplier intelligence**: seed
  `supplier_observations` per supplier to feed reliability/risk/confidence into
  the ranking and "highest-confidence" pick.
- **Landing cost is the real number.** `landed_cost = unit_price × quantity +
  shipping`. Ranking uses landed cost, not unit price.
- **Graceful degradation.** A supplier that fails a call, has no product, or is
  out of stock is either skipped or penalized — one bad supplier never breaks
  the run. Predicted discounts are `null` until enough history exists.
- **Wire plugin API keys** (in the `plugins:` YAML/env or supplier config) for
  live supplier calls; without keys the engine still runs and reports no offers.
- **Compose forward.** Feed the recommended supplier into the **finance**
  engine (as an `OpportunityInput`) and the predicted discount into **profit**
  planning; let the **event bus** trigger re-sourcing when prices change.
