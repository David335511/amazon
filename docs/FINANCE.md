# Financial Optimization Engine

Tracks **available cash, inventory value, expected payouts, credit-card
cycles, cashback, reward points, purchase commitments, storage costs, and
capital allocation** — and recommends **how many units to buy, when to buy /
reorder, and which opportunity delivers the highest capital efficiency**, with
generated **dashboards and reports**.

Everything is **configurable** via the `finance:` config block. Built on the
same conventions as the features, forecasting, documents, vision and memory
subsystems (FastAPI + PostgreSQL + alembic + DI).

---

## What it tracks

| Tracked | How |
|---|---|
| **Available cash** | Derived from the `cash_ledger`: starting cash + inflows − outflows |
| **Inventory value** | Supplied via signals (e.g. from the inventory module) |
| **Expected payouts** | Forward-looking inflow (sales pipeline) |
| **Credit-card cycles** | Billing cycle length, grace period, credit limit |
| **Cashback** | `cashback_rate` on purchases (projected) |
| **Reward points** | Points balance × `reward_points_value` = cash value |
| **Purchase commitments** | Outflow ledger rows categorized `commitment` (or signal) |
| **Storage costs** | `inventory_value × holding_cost_rate / 365 × 30` (monthly estimate) |
| **Capital allocation** | Stored per decision; drives ordering + dashboards |

From these the engine derives **net liquidity** and **usable capital**:

```
net_liquidity = available_cash
              + expected_payouts
              + available_credit        (limit − outstanding)
              + projected_cashback
              − purchase_commitments

usable_capital = max(0, net_liquidity × investable_fraction − min_cash_reserve)
```

---

## What it recommends

### How many units to buy (capital-constrained EOQ)
`economic_order_qty = sqrt(2 × annual_demand × order_cost / (unit_cost × holding_cost_rate))`,
then capped by how many units the current budget can afford and by
`max_units_per_order`. If stock is already below the reorder point it tops up
toward `reorder_point + EOQ`.

### When to buy / reorder
- **Reorder point** = demand-during-lead-time + safety stock
  `ROP = daily_demand × lead_time + z × σ_daily × √lead_time`
- **Days until reorder** = `(current_stock − ROP) / daily_demand` (0 if at/below ROP)
- **Best day to buy** = day 1 of the credit-card billing cycle (buying right
  after the cycle resets maximizes the interest-free payment float).

### Which opportunity is most capital-efficient
```
capital_efficiency = (expected_profit / capital_required) / payback_days × (1 − risk)
```
Dollars of return per dollar of capital per day, risk-adjusted. Used to rank
opportunities and allocate capital.

### Capital allocation (policies)
| Policy | Behaviour |
|---|---|
| `efficiency` (default) | Rank by capital efficiency, allocate greedily |
| `equal` | Split the budget equally (capped by each opportunity's capital need) |
| `conservative` | Rank by `efficiency × (1 − risk)` |

Each allocation is stored (`capital_allocations`) with its amount, units,
expected return, capital efficiency, risk and policy — for dashboards and audit.

---

## API

All routes under `/api/v1/finance` (API-key auth when Phase 0 security is on).

| Endpoint | Method | Purpose |
|---|---|---|
| `/finance/cash` | GET | current cash position (positional inputs as query params) |
| `/finance/transactions` | POST | record a cash movement (payout, purchase, commitment, cashback, expense, storage, refund) |
| `/finance/transactions` | GET | list the ledger (filter by category / type / entity) |
| `/finance/opportunities/evaluate` | POST | evaluate one opportunity |
| `/finance/opportunities/evaluate/batch` | POST | evaluate many (for ranking) |
| `/finance/allocate` | POST | allocate a budget across opportunities |
| `/finance/reorder` | POST | reorder decision for one entity |
| `/finance/dashboard` | GET | cash + allocation dashboard snapshot |
| `/finance/report` | GET | structured finance report (cash, ledger, allocation, config) |
| `/finance/capabilities` | GET | currency, policy, credit & rewards config |

### Record a transaction
```json
POST /api/v1/finance/transactions
{ "transaction_type": "inflow", "category": "payout", "amount": 2500.0, "description": "weekly payout" }
```

### Evaluate an opportunity
```json
POST /api/v1/finance/opportunities/evaluate
{
  "entity_type": "product",
  "entity_id": "B0TEST001",
  "unit_cost": 10.0,
  "unit_price": 15.0,
  "expected_demand": 30,
  "demand_period": "day",
  "lead_time_days": 10,
  "current_stock": 100,
  "demand_std": 5,
  "risk": 0.2
}
```
Returns `recommended_order_qty`, `capital_required`, `reorder_point`,
`safety_stock`, `days_until_reorder`, `buy_now`, `best_day_to_buy`,
`capital_efficiency`, `expected_profit`, `holding_cost`, `payback_days` and a
human-readable `reasoning`.

### Allocate capital
```json
POST /api/v1/finance/allocate
{
  "budget": 3000,
  "policy": "efficiency",
  "opportunities": [ /* OpportunityInput objects */ ]
}
```
Returns the per-opportunity allocations (amount, units, fraction, expected
return), `total_allocated`, `expected_total_return`, `policy` and `reserved`
(kept back). Omitting `budget` uses the computed **usable capital**.

---

## Storage

Two tables (Alembic migration `0009`, new head):

- **`cash_ledger`** — every cash movement (type, category, amount, entity,
  occurred_at). Available cash is derived from it.
- **`capital_allocations`** — each allocation decision (amount, units, expected
  return, capital efficiency, risk, policy, decided_at).

---

## Configuration (`finance:` block in `config/<env>.yaml`)

```yaml
finance:
  enabled: true
  currency: USD
  starting_cash: 10000.0

  credit_card_limit: 5000.0
  billing_cycle_days: 30
  grace_period_days: 21

  cashback_rate: 0.02
  reward_points_value: 0.01
  points_per_dollar: 1.0

  holding_cost_rate: 0.25      # annual % of inventory value
  order_cost: 5.0              # fixed cost per purchase order

  service_level_z: 1.65        # 95% service level for safety stock
  max_units_per_order: 1000

  allocation_policy: efficiency # efficiency | equal | conservative
  investable_fraction: 0.8      # fraction of usable capital to deploy
  min_cash_reserve: 500.0       # cash held back before allocating
  max_batch_size: 50
```

DI wiring in `app/core/dependencies.py` (`get_finance_manager`); router
`app/api/v1/finance.py`; migration `alembic/versions/0009_create_finance_tables.py`.

---

## Design notes & production guidance

- **Modular math.** All formulas live in `app/finance/engine.py` as pure,
  deterministic functions (unit-testable) — `daily_demand`, `safety_stock`,
  `reorder_point`, `economic_order_qty`, `evaluate_opportunity`,
  `allocate_opportunities`. The manager only wires them to the ledger and store.
- **Ledger is the source of cash truth.** Record every real cash movement;
  forward-looking position (inventory value, expected payouts, outstanding
  credit, reward points) is fed in via signals/query params so the engine stays
  decoupled from the rest of the platform.
- **Usable capital is the default buying budget.** Keep `min_cash_reserve` and
  `investable_fraction` tuned so the engine never spends your safety cushion.
- **Pair with the other engines.** Feed **forecasting** predictions as
  `expected_demand` into `evaluate`/`allocate`; use the **feature store** for
  the risk and demand-std inputs; let the **event bus** drive
  `record_transaction` when payouts/purchases land.
- **`efficiency` vs `conservative`.** When supply or demand is uncertain, switch
  to `conservative` (penalizes high-risk opportunities) so capital isn't
  concentrated on volatile winners.
