"""Pure financial-optimization math (deterministic, standard library only).

These functions implement the core recommendations with no I/O, so they are
directly unit-testable:

- **How many units to buy** — a capital-constrained economic order quantity
  (EOQ), capped by what is affordable from the current budget.
- **When to buy / reorder** — a reorder point (demand during lead time + safety
  stock) and the number of days until reorder; plus the optimal day within the
  credit-card billing cycle (just after the cycle resets maximizes credit
  float).
- **Which opportunity is most capital-efficient** — return per dollar per day,
  risk-adjusted. Used to rank and allocate capital.
- **Capital allocation** — greedy allocation across opportunities by the
  configured policy.

Demand periods are normalized to days (day / week / month / year).
"""

from __future__ import annotations

from typing import Any

from app.finance.config import FinanceConfig

# period name -> number of periods per day
PERIODS_PER_DAY: dict[str, float] = {
    "day": 1.0,
    "week": 1.0 / 7.0,
    "month": 1.0 / 30.0,
    "year": 1.0 / 365.0,
}


def daily_demand(expected_demand: float, demand_period: str | None) -> float:
    """Normalize a per-period demand rate to units/day."""
    factor = PERIODS_PER_DAY.get((demand_period or "day").lower(), 1.0)
    return expected_demand * factor


def daily_std(demand_std: float, demand_period: str | None) -> float:
    """Convert a per-period demand std dev to a daily std dev."""
    factor = PERIODS_PER_DAY.get((demand_period or "day").lower(), 1.0)
    days_per_period = 1.0 / factor if factor else 1.0
    if days_per_period <= 1:
        return demand_std
    return demand_std / (days_per_period**0.5)


def safety_stock(z: float, demand_std_daily: float, lead_time_days: float) -> float:
    """Safety stock = z * sigma_daily * sqrt(lead_time)."""
    return z * demand_std_daily * (max(lead_time_days, 0.0) ** 0.5)


def reorder_point(daily_d: float, lead_time_days: float, safety: float) -> float:
    """Reorder when on-hand stock covers lead-time demand + safety stock."""
    return daily_d * lead_time_days + safety


def economic_order_qty(
    daily_d: float,
    unit_cost: float,
    order_cost: float,
    holding_cost_rate: float,
) -> float:
    """Classic EOQ = sqrt(2*D*S / H), D = annual demand, H = holding cost/unit/yr."""
    annual_d = daily_d * 365.0
    holding = unit_cost * holding_cost_rate
    if annual_d <= 0 or holding <= 0:
        return 0.0
    return (2.0 * annual_d * order_cost / holding) ** 0.5


def evaluate_opportunity(
    opp: Any,
    config: FinanceConfig,
    budget: float | None,
) -> dict[str, Any]:
    """Evaluate one opportunity into a full recommendation dict.

    `opp` is an object with attributes matching `OpportunityInput`:
    unit_cost, unit_price, expected_demand, demand_period, lead_time_days,
    order_cost, current_stock, demand_std, expected_profit, payback_days, risk,
    max_units, entity_type, entity_id.
    """
    d = daily_demand(opp.expected_demand, opp.demand_period)
    dstd = daily_std(opp.demand_std, opp.demand_period)
    safety = safety_stock(config.service_level_z, dstd, opp.lead_time_days)
    rop = reorder_point(d, opp.lead_time_days, safety)

    eoq = economic_order_qty(
        d,
        opp.unit_cost,
        opp.order_cost if opp.order_cost is not None else config.order_cost,
        config.holding_cost_rate,
    )

    if opp.unit_cost > 0:
        if budget is None:
            budget_units = config.max_units_per_order  # no capital constraint
        elif budget > 0:
            budget_units = int(budget // opp.unit_cost)
        else:
            budget_units = 0
    else:
        budget_units = 0
    cap_units = min(budget_units, config.max_units_per_order)
    if opp.max_units is not None:
        cap_units = min(cap_units, opp.max_units)

    buy_now = opp.current_stock <= rop
    suggested = rop + eoq - opp.current_stock if buy_now else eoq
    qty = max(0, min(int(suggested), cap_units))

    capital_required = qty * opp.unit_cost
    margin_per_unit = (
        (opp.unit_price - opp.unit_cost) if opp.unit_price is not None else 0.0
    )
    expected_profit = (
        opp.expected_profit
        if opp.expected_profit is not None
        else margin_per_unit * qty
    )
    days_to_sell = (qty / d) if d > 0 else 0.0
    payback_days = (
        opp.payback_days
        if opp.payback_days is not None
        else (opp.lead_time_days + days_to_sell)
    )
    holding_cost = (
        (qty / 2.0)
        * opp.unit_cost
        * config.holding_cost_rate
        * (payback_days / 365.0)
    )

    if capital_required > 0 and payback_days > 0:
        capital_efficiency = (
            (expected_profit / capital_required) / payback_days * (1.0 - opp.risk)
        )
    else:
        capital_efficiency = 0.0

    days_until_reorder = max(0.0, (opp.current_stock - rop) / d) if d > 0 else 0.0

    reasoning = _reasoning(
        buy_now, rop, opp.current_stock, qty, capital_efficiency,
        expected_profit, payback_days, opp.risk,
    )

    return {
        "entity_type": opp.entity_type,
        "entity_id": opp.entity_id,
        "unit_cost": opp.unit_cost,
        "recommended_order_qty": qty,
        "capital_required": capital_required,
        "reorder_point": round(rop, 2),
        "safety_stock": round(safety, 2),
        "days_until_reorder": round(days_until_reorder, 1),
        "buy_now": buy_now,
        "best_day_to_buy": 1,  # start of the billing cycle -> max credit float
        "capital_efficiency": round(capital_efficiency, 6),
        "expected_profit": round(expected_profit, 2),
        "holding_cost": round(holding_cost, 2),
        "payback_days": round(payback_days, 1),
        "risk": opp.risk,
        "reasoning": reasoning,
    }


def allocate_opportunities(
    items: list[Any],
    config: FinanceConfig,
    budget: float,
    policy: str | None = None,
) -> dict[str, Any]:
    """Allocate a capital budget across opportunities by the configured policy.

    Returns ``{allocations, total_allocated, expected_total_return, policy,
    reserved}`` where each allocation references the evaluated opportunity.
    """
    evals = [evaluate_opportunity(i, config, budget) for i in items]

    policy = policy or config.allocation_policy
    if policy == "equal":
        ranked = list(evals)
    elif policy == "conservative":
        ranked = sorted(
            evals, key=lambda e: e["capital_efficiency"] * (1.0 - e["risk"]), reverse=True
        )
    else:  # efficiency (default)
        ranked = sorted(evals, key=lambda e: e["capital_efficiency"], reverse=True)

    remaining = float(budget)
    n = len(ranked)
    allocations: list[dict[str, Any]] = []
    for ev in ranked:
        cap = ev["capital_required"]
        if policy == "equal" and n:
            share = budget / n
            alloc = min(cap, share, remaining)
        else:
            alloc = min(cap, remaining)
        alloc = max(0.0, alloc)
        remaining -= alloc
        units = (alloc / ev["unit_cost"]) if ev["unit_cost"] > 0 else 0.0
        margin_rate = (
            (ev["expected_profit"] / ev["capital_required"])
            if ev["capital_required"] > 0
            else 0.0
        )
        allocations.append(
            {
                "entity_type": ev["entity_type"],
                "entity_id": ev["entity_id"],
                "allocated": round(alloc, 2),
                "units": round(units, 2),
                "fraction": round(alloc / budget, 4) if budget else 0.0,
                "capital_efficiency": ev["capital_efficiency"],
                "expected_return": round(alloc * margin_rate, 2),
                "risk": ev["risk"],
                "recommended_order_qty": ev["recommended_order_qty"],
            }
        )

    total_allocated = sum(a["allocated"] for a in allocations)
    return {
        "allocations": allocations,
        "total_allocated": round(total_allocated, 2),
        "expected_total_return": round(sum(a["expected_return"] for a in allocations), 2),
        "policy": policy,
        "reserved": round(budget - total_allocated, 2),
    }


def _reasoning(
    buy_now: bool,
    rop: float,
    stock: float,
    qty: int,
    efficiency: float,
    profit: float,
    payback_days: float,
    risk: float,
) -> str:
    trigger = "Order now: stock is at/below the reorder point." if buy_now else "Stock is above the reorder point; no immediate order required."
    return (
        f"{trigger} Reorder point {rop:.1f}, current stock {stock:.1f}. "
        f"Recommended order quantity {qty} units. "
        f"Capital efficiency {efficiency:.4f} ($ return per $ per day, "
        f"risk-adjusted {risk:.2f}), expected profit ${profit:.2f}, "
        f"payback ~{payback_days:.1f} days."
    )
