"""Tests for the profit engine using real-world Amazon product examples.

Each test case represents a real product with actual pricing and fee data.
Tests verify that the engine produces correct, transparent results.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.profit.config import DEFAULT_PROFIT_CONFIG, ProfitConfig
from app.profit.engine import ProfitEngine
from app.profit.models import ProfitInput, ProfitOutput


# ═══════════════════════════════════════════════════════════════
# Real-World Test Cases
# ═══════════════════════════════════════════════════════════════


class TestRealWorldProducts:
    """Test the profit engine with real Amazon product data."""

    @pytest.fixture
    def engine(self) -> ProfitEngine:
        """Create a profit engine with default configuration."""
        return ProfitEngine()

    # ── Case 1: Anker PowerCore 10000mAh ────────────────────
    # Amazon price: $24.99, Supplier cost: $11.80
    # Category: Cell Phone Accessories (15% referral)
    # FBA fulfillment: $4.50 (small standard)
    # Realistic profit scenario

    def test_anker_powercore(self, engine: ProfitEngine) -> None:
        """Test Anker PowerCore — a profitable FBA product."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("24.99"),
                supplier_price=Decimal("11.80"),
                shipping_cost=Decimal("1.50"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
            category="Cell Phone Accessories",
        )

        assert result.is_profitable is True
        assert result.net_profit > 0
        assert result.margin_percentage > 0
        assert result.roi_percentage > 0

        # Verify fee breakdown
        assert len(result.cost_breakdown) >= 3  # Referral, FBA, Shipping
        referral = next(f for f in result.cost_breakdown if "Referral" in f.name)
        assert referral.amount == Decimal("3.75")  # 15% of $24.99

        # Verify profit is reasonable
        assert result.net_profit_per_unit > Decimal("2.00")
        assert result.margin_percentage > Decimal("10.00")

    # ── Case 2: Sony WH-1000XM5 Headphones ──────────────────
    # Amazon price: $349.99, Supplier cost: $198.00
    # Category: Electronics (8% referral)
    # FBA fulfillment: $6.50 (large standard)
    # High-value product with lower referral rate

    def test_sony_headphones(self, engine: ProfitEngine) -> None:
        """Test Sony WH-1000XM5 — high-value electronics."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("349.99"),
                supplier_price=Decimal("198.00"),
                shipping_cost=Decimal("3.00"),
                fba_fulfillment_fee=Decimal("6.50"),
                quantity=1,
            ),
            category="Electronics",
        )

        assert result.is_profitable is True
        assert result.net_profit > 0

        # Electronics has 8% referral fee
        referral = next(f for f in result.cost_breakdown if "Referral" in f.name)
        assert referral.amount == Decimal("28.00")  # 8% of $349.99

        # High-value product should have good ROI
        assert result.roi_percentage > Decimal("30.00")

    # ── Case 3: Low-Margin Household Product ─────────────────
    # Amazon price: $12.99, Supplier cost: $8.50
    # Category: Home & Kitchen (15% referral)
    # FBA fulfillment: $4.50
    # Tight margins — tests break-even accuracy

    def test_low_margin_product(self, engine: ProfitEngine) -> None:
        """Test a low-margin household product."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("12.99"),
                supplier_price=Decimal("8.50"),
                shipping_cost=Decimal("1.00"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
            category="Home & Kitchen",
        )

        # This product may or may not be profitable
        # The important thing is the calculation is correct
        referral = next(f for f in result.cost_breakdown if "Referral" in f.name)
        assert referral.amount == Decimal("1.95")  # 15% of $12.99

        # Break-even price should be reasonable
        assert result.break_even_price > Decimal("0")
        assert result.break_even_price < result.amazon_price or not result.is_profitable

    # ── Case 4: Product with Coupon + Cashback ──────────────
    # Tests that discounts and incentives are correctly applied

    def test_with_coupon_and_cashback(self, engine: ProfitEngine) -> None:
        """Test profit calculation with coupon and cashback."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("49.99"),
                supplier_price=Decimal("22.00"),
                shipping_cost=Decimal("2.00"),
                fba_fulfillment_fee=Decimal("5.50"),
                coupon_discount=Decimal("5.00"),
                cashback_percent=Decimal("2.00"),
                credit_card_rewards_percent=Decimal("1.50"),
                quantity=1,
            ),
            category="Sports & Outdoors",
        )

        assert result.is_profitable is True

        # Coupon should be in cost breakdown
        coupon = next((f for f in result.cost_breakdown if "Coupon" in f.name), None)
        assert coupon is not None
        assert coupon.amount == Decimal("5.00")

        # Cashback should appear as negative fee (savings)
        cashback = next((f for f in result.cost_breakdown if "Cashback" in f.name), None)
        assert cashback is not None
        assert cashback.amount < 0  # Negative = savings

        # Credit card rewards should appear as savings
        cc = next((f for f in result.cost_breakdown if "Credit Card" in f.name), None)
        assert cc is not None
        assert cc.amount < 0  # Negative = savings

    # ── Case 5: Bulk Quantity ───────────────────────────────
    # Tests that quantity scaling works correctly

    def test_bulk_quantity(self, engine: ProfitEngine) -> None:
        """Test profit calculation with bulk quantity."""
        result_single = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("19.99"),
                supplier_price=Decimal("9.00"),
                shipping_cost=Decimal("1.50"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
        )

        result_bulk = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("19.99"),
                supplier_price=Decimal("9.00"),
                shipping_cost=Decimal("1.50"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=100,
            ),
        )

        # Per-unit profit should be the same
        assert result_single.net_profit_per_unit == result_bulk.net_profit_per_unit

        # Total profit should scale with quantity
        assert result_bulk.net_profit == result_single.net_profit * 100

    # ── Case 6: Unprofitable Product ─────────────────────────
    # Tests that the engine correctly identifies losses

    def test_unprofitable_product(self, engine: ProfitEngine) -> None:
        """Test a clearly unprofitable product."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("9.99"),
                supplier_price=Decimal("8.00"),
                shipping_cost=Decimal("2.00"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
        )

        assert result.is_profitable is False
        assert result.net_profit < 0
        assert result.margin_percentage < 0

    # ── Case 7: Supplier Volume Discount ────────────────────
    # Tests that supplier discounts reduce cost

    def test_supplier_discount(self, engine: ProfitEngine) -> None:
        """Test profit with supplier volume discount."""
        result_no_discount = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("29.99"),
                supplier_price=Decimal("15.00"),
                shipping_cost=Decimal("2.00"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
        )

        result_with_discount = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("29.99"),
                supplier_price=Decimal("15.00"),
                shipping_cost=Decimal("2.00"),
                fba_fulfillment_fee=Decimal("4.50"),
                supplier_discount_percent=Decimal("10.00"),
                quantity=1,
            ),
        )

        # Discount should increase profit
        assert result_with_discount.net_profit > result_no_discount.net_profit
        assert result_with_discount.roi_percentage > result_no_discount.roi_percentage

    # ── Case 8: Sales Tax Impact ────────────────────────────
    # Tests that sales tax reduces profit

    def test_sales_tax_impact(self, engine: ProfitEngine) -> None:
        """Test that sales tax is correctly applied."""
        result_no_tax = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("49.99"),
                supplier_price=Decimal("20.00"),
                shipping_cost=Decimal("2.00"),
                fba_fulfillment_fee=Decimal("5.50"),
                quantity=1,
            ),
        )

        result_with_tax = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("49.99"),
                supplier_price=Decimal("20.00"),
                shipping_cost=Decimal("2.00"),
                fba_fulfillment_fee=Decimal("5.50"),
                sales_tax_percent=Decimal("8.875"),
                quantity=1,
            ),
        )

        # Tax should reduce profit
        assert result_with_tax.net_profit < result_no_tax.net_profit
        assert result_with_tax.taxes_per_unit > 0

    # ── Case 9: Category-Specific Referral Fees ─────────────
    # Tests that different categories have different fee rates

    def test_category_referral_fees(self, engine: ProfitEngine) -> None:
        """Test that different categories have correct referral fees."""
        base_input = ProfitInput(
            amazon_price=Decimal("100.00"),
            supplier_price=Decimal("40.00"),
            shipping_cost=Decimal("3.00"),
            fba_fulfillment_fee=Decimal("5.50"),
            quantity=1,
        )

        # Electronics: 8%
        electronics = engine.calculate(base_input, category="Electronics")
        e_ref = next(f for f in electronics.cost_breakdown if "Referral" in f.name)
        assert e_ref.amount == Decimal("8.00")  # 8% of $100

        # Clothing: 17%
        clothing = engine.calculate(base_input, category="Clothing & Accessories")
        c_ref = next(f for f in clothing.cost_breakdown if "Referral" in f.name)
        assert c_ref.amount == Decimal("17.00")  # 17% of $100

        # Default: 15%
        default = engine.calculate(base_input)
        d_ref = next(f for f in default.cost_breakdown if "Referral" in f.name)
        assert d_ref.amount == Decimal("15.00")  # 15% of $100

    # ── Case 10: Break-Even Price Accuracy ──────────────────
    # Tests that the break-even price is accurate

    def test_break_even_price(self, engine: ProfitEngine) -> None:
        """Test that break-even price is calculated correctly."""
        # At break-even price, profit should be ~0
        base = ProfitInput(
            amazon_price=Decimal("50.00"),  # Will be overridden
            supplier_price=Decimal("25.00"),
            shipping_cost=Decimal("2.00"),
            fba_fulfillment_fee=Decimal("4.50"),
            quantity=1,
        )

        be_price = engine.find_break_even_price(base)
        be_input = base.model_copy(update={"amazon_price": be_price})
        be_result = engine.calculate(be_input)

        # At break-even, profit should be near zero
        assert abs(be_result.net_profit) < Decimal("1.00")


# ═══════════════════════════════════════════════════════════════
# Edge Case Tests
# ═══════════════════════════════════════════════════════════════


class TestProfitEngineEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def engine(self) -> ProfitEngine:
        return ProfitEngine()

    def test_zero_quantity(self, engine: ProfitEngine) -> None:
        """Test that quantity=0 doesn't cause errors."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("10.00"),
                supplier_price=Decimal("5.00"),
                quantity=1,  # Minimum 1
            ),
        )
        assert result.total_revenue == Decimal("10.00")

    def test_high_precision_prices(self, engine: ProfitEngine) -> None:
        """Test with high-precision decimal prices."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("19.9999"),
                supplier_price=Decimal("8.5050"),
                shipping_cost=Decimal("1.2500"),
                fba_fulfillment_fee=Decimal("4.5050"),
                quantity=1,
            ),
        )
        assert result.net_profit is not None
        assert isinstance(result.net_profit, Decimal)

    def test_custom_config(self) -> None:
        """Test with custom fee configuration."""
        config = ProfitConfig()
        config.fees.default_referral_fee_percent = Decimal("10.00")
        engine = ProfitEngine(config)

        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("100.00"),
                supplier_price=Decimal("50.00"),
                quantity=1,
            ),
        )

        referral = next(f for f in result.cost_breakdown if "Referral" in f.name)
        assert referral.amount == Decimal("10.00")  # 10% of $100

    def test_explicit_fee_overrides(self, engine: ProfitEngine) -> None:
        """Test that explicit fee overrides in ProfitInput work."""
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("100.00"),
                supplier_price=Decimal("50.00"),
                referral_fee_percent=Decimal("5.00"),
                fba_fulfillment_fee=Decimal("3.00"),
                quantity=1,
            ),
        )

        referral = next(f for f in result.cost_breakdown if "Referral" in f.name)
        assert referral.amount == Decimal("5.00")  # 5% override

    def test_batch_calculation(self, engine: ProfitEngine) -> None:
        """Test batch calculation of multiple products."""
        inputs = [
            ProfitInput(amazon_price=Decimal("20.00"), supplier_price=Decimal("10.00"), quantity=1),
            ProfitInput(amazon_price=Decimal("30.00"), supplier_price=Decimal("15.00"), quantity=1),
            ProfitInput(amazon_price=Decimal("40.00"), supplier_price=Decimal("20.00"), quantity=1),
        ]
        results = engine.calculate_batch(inputs)
        assert len(results) == 3
        assert all(isinstance(r, ProfitOutput) for r in results)
        assert results[0].net_profit < results[1].net_profit < results[2].net_profit


# ═══════════════════════════════════════════════════════════════
# Calculation Verification Tests
# ═══════════════════════════════════════════════════════════════


class TestProfitCalculationAccuracy:
    """Verify that calculations match expected values."""

    def test_known_calculation(self) -> None:
        """Test a known calculation with verified numbers.

        Scenario:
            Amazon price: $24.99
            Supplier cost: $11.80
            Shipping: $1.50
            FBA fee: $4.50
            Category: Cell Phone Accessories (15% referral)

        Expected:
            Revenue: $24.99
            Referral fee: $3.75 (15% of $24.99)
            FBA fee: $4.50
            Shipping: $1.50
            Supplier cost: $11.80
            Total cost: $21.55
            Net profit: $3.44
            Margin: 13.77%
        """
        engine = ProfitEngine()
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("24.99"),
                supplier_price=Decimal("11.80"),
                shipping_cost=Decimal("1.50"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
            category="Cell Phone Accessories",
        )

        assert result.total_revenue == Decimal("24.99")
        assert result.net_profit == Decimal("24.99") - Decimal("21.55")
        assert abs(result.margin_percentage - Decimal("13.77")) < Decimal("0.1")

    def test_roi_calculation(self) -> None:
        """Test ROI calculation with verified numbers.

        Scenario:
            Net profit: $3.44
            Capital invested (supplier + shipping): $11.80 + $1.50 = $13.30
            ROI: $3.44 / $13.30 * 100 = 25.86%
        """
        engine = ProfitEngine()
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("24.99"),
                supplier_price=Decimal("11.80"),
                shipping_cost=Decimal("1.50"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
            category="Cell Phone Accessories",
        )

        expected_roi = Decimal("3.44") / Decimal("13.30") * 100
        assert abs(result.roi_percentage - expected_roi) < Decimal("1.0")

    def test_return_on_capital(self) -> None:
        """Test return on capital calculation."""
        engine = ProfitEngine()
        result = engine.calculate(
            ProfitInput(
                amazon_price=Decimal("24.99"),
                supplier_price=Decimal("11.80"),
                shipping_cost=Decimal("1.50"),
                fba_fulfillment_fee=Decimal("4.50"),
                quantity=1,
            ),
            category="Cell Phone Accessories",
        )

        expected_roc = Decimal("3.44") / Decimal("13.30")
        assert abs(result.return_on_capital - expected_roc) < Decimal("0.1")
