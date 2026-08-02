"""Profit engine — calculates profit, ROI, margin, break-even, and return on capital.

Design decisions:
- Every fee component is itemized in the output for full transparency.
- All calculations use Decimal for monetary precision.
- The engine is stateless — all configuration is passed in.
- Fee rates can be overridden per-calculation via ProfitInput.
- Break-even price accounts for all variable costs.
- ROI uses total capital invested (inventory + shipping).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.profit.config import DEFAULT_PROFIT_CONFIG, ProfitConfig
from app.profit.models import (
    FeeCategory,
    FeeComponent,
    ProfitInput,
    ProfitOutput,
)


class ProfitEngine:
    """Calculates profit, ROI, margin, break-even, and return on capital.

    Usage:
        engine = ProfitEngine()
        result = engine.calculate(input)
        print(f"Net profit: {result.net_profit}")
        print(f"ROI: {result.roi_percentage}%")
    """

    def __init__(self, config: ProfitConfig | None = None) -> None:
        """Initialize the profit engine.

        Args:
            config: Profit configuration. Uses defaults if None.
        """
        self._config = config or DEFAULT_PROFIT_CONFIG

    def calculate(
        self,
        input_data: ProfitInput,
        category: str | None = None,
    ) -> ProfitOutput:
        """Calculate profit metrics for a product.

        Args:
            input_data: Profit calculation inputs.
            category: Amazon product category (for category-specific fees).

        Returns:
            Complete profit output with all metrics.
        """
        qty = input_data.quantity
        price = input_data.amazon_price
        cost = input_data.supplier_price
        currency = input_data.currency

        # ── Revenue ─────────────────────────────────────────
        total_revenue = price * qty
        revenue_per_unit = price

        # ── Supplier Discount ────────────────────────────────
        effective_cost = cost * (1 - input_data.supplier_discount_percent / 100)
        total_supplier_cost = effective_cost * qty

        # ── Fee Breakdown ───────────────────────────────────
        fees: list[FeeComponent] = []

        # 1. Referral fee
        ref_pct, ref_min = self._get_referral_fee(input_data, category)
        referral_fee_per_unit = max(price * ref_pct / 100, ref_min)
        total_referral_fee = referral_fee_per_unit * qty
        fees.append(FeeComponent(
            name="Referral Fee",
            category=FeeCategory.PERCENTAGE,
            amount=total_referral_fee,
            description=f"{ref_pct}% of ${price} = ${price * ref_pct / 100:.2f}"
            f"{' (min: $' + str(ref_min) + ')' if ref_min > 0 else ''}",
        ))

        # 2. FBA fulfillment fee
        fba_fee_per_unit = input_data.fba_fulfillment_fee or self._config.fees.large_standard_fulfillment
        total_fba_fee = fba_fee_per_unit * qty
        if fba_fee_per_unit > 0:
            fees.append(FeeComponent(
                name="FBA Fulfillment Fee",
                category=FeeCategory.FIXED,
                amount=total_fba_fee,
                description=f"${fba_fee_per_unit} per unit × {qty} units",
            ))

        # 3. FBA storage fee
        storage_fee_per_unit = input_data.fba_storage_fee or Decimal("0")
        total_storage_fee = storage_fee_per_unit * qty
        if storage_fee_per_unit > 0:
            fees.append(FeeComponent(
                name="FBA Storage Fee",
                category=FeeCategory.FIXED,
                amount=total_storage_fee,
                description=f"${storage_fee_per_unit} per unit × {qty} units",
            ))

        # 4. Closing fee
        total_closing_fee = input_data.closing_fee * qty
        if input_data.closing_fee > 0:
            fees.append(FeeComponent(
                name="Closing Fee",
                category=FeeCategory.FIXED,
                amount=total_closing_fee,
                description=f"${input_data.closing_fee} per unit × {qty} units",
            ))

        # 5. Shipping cost
        total_shipping = input_data.shipping_cost * qty
        if input_data.shipping_cost > 0:
            fees.append(FeeComponent(
                name="Shipping Cost",
                category=FeeCategory.FIXED,
                amount=total_shipping,
                description=f"${input_data.shipping_cost} per unit × {qty} units",
            ))

        # 6. Prep cost
        total_prep = input_data.prep_cost * qty
        if input_data.prep_cost > 0:
            fees.append(FeeComponent(
                name="Prep/Labeling Cost",
                category=FeeCategory.FIXED,
                amount=total_prep,
                description=f"${input_data.prep_cost} per unit × {qty} units",
            ))

        # 7. Other costs
        total_other = input_data.other_costs * qty
        if input_data.other_costs > 0:
            fees.append(FeeComponent(
                name="Other Costs",
                category=FeeCategory.FIXED,
                amount=total_other,
                description=f"${input_data.other_costs} per unit × {qty} units",
            ))

        # 8. Sales tax
        tax_percent = input_data.sales_tax_percent
        total_tax = total_revenue * tax_percent / 100
        if tax_percent > 0:
            fees.append(FeeComponent(
                name="Sales Tax",
                category=FeeCategory.PERCENTAGE,
                amount=total_tax,
                description=f"{tax_percent}% of ${total_revenue} = ${total_tax:.2f}",
            ))

        # 9. Coupon discount
        total_coupon = input_data.coupon_discount * qty
        if input_data.coupon_discount > 0:
            fees.append(FeeComponent(
                name="Coupon Discount",
                category=FeeCategory.FIXED,
                amount=total_coupon,
                description=f"${input_data.coupon_discount} per unit × {qty} units",
            ))

        # ── Discounts & Incentives (negative fees) ──────────
        total_cashback = total_revenue * input_data.cashback_percent / 100
        if input_data.cashback_percent > 0:
            fees.append(FeeComponent(
                name="Cashback (savings)",
                category=FeeCategory.PERCENTAGE,
                amount=-total_cashback,
                description=f"{input_data.cashback_percent}% of ${total_revenue} = -${total_cashback:.2f}",
            ))

        total_cc_rewards = total_revenue * input_data.credit_card_rewards_percent / 100
        if input_data.credit_card_rewards_percent > 0:
            fees.append(FeeComponent(
                name="Credit Card Rewards (savings)",
                category=FeeCategory.PERCENTAGE,
                amount=-total_cc_rewards,
                description=f"{input_data.credit_card_rewards_percent}% of ${total_revenue} = -${total_cc_rewards:.2f}",
            ))

        # ── Totals ──────────────────────────────────────────
        total_amazon_fees = total_referral_fee + total_fba_fee + total_storage_fee + total_closing_fee
        total_discounts = total_coupon
        total_savings = total_cashback + total_cc_rewards

        total_cost = (
            total_supplier_cost
            + total_shipping
            + total_prep
            + total_other
            + total_amazon_fees
            + total_tax
            + total_discounts
            - total_savings
        )

        cost_per_unit = total_cost / qty if qty > 0 else Decimal("0")

        # ── Profit Metrics ──────────────────────────────────
        gross_profit = total_revenue - total_supplier_cost
        net_profit = total_revenue - total_cost
        net_profit_per_unit = net_profit / qty if qty > 0 else Decimal("0")

        # ── Percentage Metrics ──────────────────────────────
        margin_pct = (net_profit / total_revenue * 100) if total_revenue > 0 else Decimal("0")
        markup_pct = ((total_revenue - total_cost) / total_cost * 100) if total_cost > 0 else Decimal("0")

        # ── Capital Invested & ROI ──────────────────────────
        capital = input_data.capital_invested or (total_supplier_cost + total_shipping)
        roi_pct = (net_profit / capital * 100) if capital > 0 else Decimal("0")
        roc = (net_profit / capital) if capital > 0 else Decimal("0")

        # ── Break-even ──────────────────────────────────────
        # Fixed costs that don't vary with quantity
        fixed_costs = total_shipping + total_prep + total_other + total_fba_fee + total_storage_fee + total_closing_fee

        # Variable costs per unit
        var_cost_per_unit = effective_cost + input_data.shipping_cost + input_data.prep_cost + input_data.other_costs

        # Break-even price: the price at which net profit = 0
        # net_profit = price * qty - (var_cost_per_unit * qty + fixed_costs + ref_fee + tax)
        # For break-even with qty = 1:
        # 0 = price - var_cost_per_unit - ref_fee - tax
        # ref_fee = max(price * ref_pct / 100, ref_min)
        # tax = price * tax_percent / 100
        # 0 = price - var_cost_per_unit - max(price * ref_pct / 100, ref_min) - price * tax_percent / 100

        # Simple break-even (ignoring min fee for simplicity)
        effective_rate = ref_pct / 100 + tax_percent / 100
        if effective_rate < 1:
            be_price = (var_cost_per_unit + ref_min) / (1 - effective_rate)
        else:
            be_price = var_cost_per_unit + ref_min

        # Break-even quantity: units needed at current price
        if net_profit_per_unit > 0:
            be_qty = 1  # Already profitable at 1 unit
        else:
            # Need to cover fixed costs
            contribution = net_profit_per_unit
            if contribution > 0:
                be_qty = 1
            else:
                be_qty = 0  # Cannot break even at this price

        return ProfitOutput(
            total_revenue=total_revenue,
            revenue_per_unit=revenue_per_unit,
            total_cost=total_cost,
            cost_per_unit=cost_per_unit,
            cost_breakdown=fees,
            gross_profit=gross_profit,
            net_profit=net_profit,
            net_profit_per_unit=net_profit_per_unit,
            margin_percentage=round(margin_pct, 2),
            roi_percentage=round(roi_pct, 2),
            markup_percentage=round(markup_pct, 2),
            break_even_price=round(be_price, 2),
            break_even_quantity=max(1, be_qty),
            return_on_capital=round(roc, 4),
            capital_invested=capital,
            amazon_fees_per_unit=total_amazon_fees / qty if qty > 0 else Decimal("0"),
            taxes_per_unit=total_tax / qty if qty > 0 else Decimal("0"),
            discounts_per_unit=total_discounts / qty if qty > 0 else Decimal("0"),
            currency=currency,
            is_profitable=net_profit > 0,
        )

    def _get_referral_fee(
        self,
        input_data: ProfitInput,
        category: str | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Get the effective referral fee percentage and minimum.

        Priority:
        1. Explicit override in ProfitInput
        2. Category-specific schedule
        3. Default rate
        """
        if input_data.referral_fee_percent is not None:
            return input_data.referral_fee_percent, input_data.referral_fee_min or Decimal("0")

        return self._config.get_referral_fee(category)

    def calculate_batch(
        self,
        inputs: list[ProfitInput],
        category: str | None = None,
    ) -> list[ProfitOutput]:
        """Calculate profit for multiple products.

        Args:
            inputs: List of profit calculation inputs.
            category: Amazon product category.

        Returns:
            List of profit outputs in the same order.
        """
        return [self.calculate(inp, category) for inp in inputs]

    def find_break_even_price(
        self,
        input_data: ProfitInput,
        category: str | None = None,
        precision: Decimal = Decimal("0.01"),
    ) -> Decimal:
        """Find the exact break-even price using binary search.

        Args:
            input_data: Base profit inputs (amazon_price is ignored).
            category: Amazon product category.
            precision: Price precision for the search.

        Returns:
            Break-even price.
        """
        low = Decimal("0.01")
        high = input_data.supplier_price * 10  # Upper bound

        while high - low > precision:
            mid = (low + high) / 2
            test_input = input_data.model_copy(update={"amazon_price": mid})
            result = self.calculate(test_input, category)
            if result.is_profitable:
                high = mid
            else:
                low = mid

        return high
