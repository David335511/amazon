"""Individual sourcing rules — each evaluates one dimension of product opportunity.

Design decisions:
- Each rule is a standalone class with a single `evaluate()` method.
- Rules receive the data they need (no hidden dependencies).
- Every rule returns a RuleResult with score, passed/failed, and reasoning.
- Scores are normalized to 0.0–1.0 using configurable target thresholds.
- Rules are stateless — all configuration is passed in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from app.sourcing.models import (
    RuleResult,
    RuleSeverity,
    SourcingConfig,
)


class BaseSourcingRule(ABC):
    """Abstract base for all sourcing rules."""

    rule_name: str = ""
    display_name: str = ""

    @abstractmethod
    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        """Evaluate a product against this rule.

        Args:
            config: Sourcing configuration with thresholds and weights.
            data: Dict of pre-computed product data needed by this rule.

        Returns:
            RuleResult with score, passed/failed, and reasoning.
        """

    def _normalize_score(
        self,
        actual: Decimal,
        minimum: Decimal,
        target: Decimal,
    ) -> Decimal:
        """Normalize a value to a 0.0–1.0 score.

        Scoring formula:
        - Below minimum: score = actual / minimum * 0.5 (0 to 0.5)
        - At minimum: score = 0.5
        - Between minimum and target: linear interpolation 0.5 to 1.0
        - At or above target: score = 1.0

        This ensures:
        - Below minimum always scores < 0.5 (failing range)
        - At minimum scores exactly 0.5 (borderline)
        - Above minimum scores > 0.5 (passing range)
        - At target scores 1.0 (perfect)
        """
        if actual <= Decimal("0"):
            return Decimal("0")

        if actual < minimum:
            # Below minimum: 0 to 0.5
            return (actual / minimum * Decimal("0.5")).quantize(Decimal("0.0001"))

        if actual >= target:
            return Decimal("1.0")

        # Between minimum and target: 0.5 to 1.0
        progress = (actual - minimum) / (target - minimum)
        return (Decimal("0.5") + progress * Decimal("0.5")).quantize(Decimal("0.0001"))


# ═══════════════════════════════════════════════════════════════
# Minimum ROI Rule
# ═══════════════════════════════════════════════════════════════


class MinimumRoiRule(BaseSourcingRule):
    """Evaluates whether the product's ROI meets the minimum threshold.

    ROI = (Net Profit / Total Cost) * 100

    Higher ROI means more return per dollar invested. This is the
    single most important metric for sourcing decisions.
    """

    rule_name = "minimum_roi"
    display_name = "Minimum ROI"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        roi_pct = data.get("roi_percentage", Decimal("0"))
        if isinstance(roi_pct, (int, float)):
            roi_pct = Decimal(str(roi_pct))

        score = self._normalize_score(
            actual=roi_pct,
            minimum=config.min_roi_percentage,
            target=config.target_roi_percentage,
        )
        passed = roi_pct >= config.min_roi_percentage

        # Build reasoning
        if passed:
            if roi_pct >= config.target_roi_percentage:
                summary = f"Excellent ROI of {roi_pct:.1f}% (target: {config.target_roi_percentage:.0f}%)"
            else:
                summary = f"Good ROI of {roi_pct:.1f}% (minimum: {config.min_roi_percentage:.0f}%)"
        else:
            summary = f"ROI of {roi_pct:.1f}% is below minimum of {config.min_roi_percentage:.0f}%"

        details = (
            f"ROI measures return on capital invested. "
            f"At {roi_pct:.1f}%, each $100 invested returns ${roi_pct:.1f} in profit. "
            f"Target ROI is {config.target_roi_percentage:.0f}% for a perfect score."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.roi_severity,
            weight=config.weights.roi_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.roi_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"{roi_pct:.1f}%",
            threshold_value=f"{config.min_roi_percentage:.0f}%",
            target_value=f"{config.target_roi_percentage:.0f}%",
            summary=summary,
            details=details,
            data_quality="Calculated from latest Amazon price and supplier cost data",
        )


# ═══════════════════════════════════════════════════════════════
# Minimum Profit Rule
# ═══════════════════════════════════════════════════════════════


class MinimumProfitRule(BaseSourcingRule):
    """Evaluates whether net profit per unit meets the minimum threshold.

    Net Profit = Amazon Price - Total Cost (including all fees)

    Low-profit products are risky because small price changes can
    wipe out margins. Higher profit provides a buffer.
    """

    rule_name = "minimum_profit"
    display_name = "Minimum Profit"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        net_profit = data.get("net_profit", Decimal("0"))
        if isinstance(net_profit, (int, float)):
            net_profit = Decimal(str(net_profit))

        score = self._normalize_score(
            actual=net_profit,
            minimum=config.min_net_profit,
            target=config.target_net_profit,
        )
        passed = net_profit >= config.min_net_profit

        if passed:
            if net_profit >= config.target_net_profit:
                summary = f"Strong profit of ${net_profit:.2f}/unit (target: ${config.target_net_profit:.2f})"
            else:
                summary = f"Profit of ${net_profit:.2f}/unit meets minimum of ${config.min_net_profit:.2f}"
        else:
            summary = f"Profit of ${net_profit:.2f}/unit is below minimum of ${config.min_net_profit:.2f}"

        details = (
            f"Net profit per unit after all costs including Amazon fees, "
            f"shipping, and cost of goods. At ${net_profit:.2f}/unit, "
            f"selling 1000 units yields ${net_profit * 1000:.2f} total profit."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.profit_severity,
            weight=config.weights.profit_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.profit_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"${net_profit:.2f}",
            threshold_value=f"${config.min_net_profit:.2f}",
            target_value=f"${config.target_net_profit:.2f}",
            summary=summary,
            details=details,
            data_quality="Calculated from latest price, cost, and fee data",
        )


# ═══════════════════════════════════════════════════════════════
# Minimum Sales Rule
# ═══════════════════════════════════════════════════════════════


class MinimumSalesRule(BaseSourcingRule):
    """Evaluates whether estimated monthly sales meet the minimum threshold.

    Products with higher sales volume are more likely to generate
    consistent revenue. Low-volume products may not be worth the
    effort of listing and managing inventory.
    """

    rule_name = "minimum_sales"
    display_name = "Minimum Sales Volume"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        monthly_sales = data.get("estimated_monthly_sales", 0)
        if not isinstance(monthly_sales, (int, Decimal)):
            monthly_sales = int(monthly_sales)  # type: ignore[arg-type]
        monthly_sales_val = Decimal(str(monthly_sales))

        score = self._normalize_score(
            actual=monthly_sales_val,
            minimum=Decimal(str(config.min_monthly_sales)),
            target=Decimal(str(config.target_monthly_sales)),
        )
        passed = monthly_sales >= config.min_monthly_sales

        daily = monthly_sales / 30 if monthly_sales > 0 else 0

        if passed:
            if monthly_sales >= config.target_monthly_sales:
                summary = f"High demand: ~{monthly_sales:,}/month (target: {config.target_monthly_sales:,})"
            else:
                summary = f"Moderate demand: ~{monthly_sales:,}/month (minimum: {config.min_monthly_sales:,})"
        else:
            summary = f"Low demand: ~{monthly_sales:,}/month is below minimum of {config.min_monthly_sales:,}"

        details = (
            f"Estimated {monthly_sales:,} units sold per month "
            f"(~{daily:.0f}/day). "
            f"At ${data.get('net_profit', 0):.2f} profit/unit, "
            f"this represents ~${monthly_sales * float(data.get('net_profit', 0)):,.0f}/month "
            f"in potential profit."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.sales_severity,
            weight=config.weights.sales_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.sales_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"{monthly_sales:,}/month",
            threshold_value=f"{config.min_monthly_sales:,}/month",
            target_value=f"{config.target_monthly_sales:,}/month",
            summary=summary,
            details=details,
            data_quality="Estimated from Keepa sales data (may vary by season)",
        )


# ═══════════════════════════════════════════════════════════════
# Competition Rule
# ═══════════════════════════════════════════════════════════════


class CompetitionRule(BaseSourcingRule):
    """Evaluates the competitive landscape.

    Too few sellers may indicate low demand or restricted categories.
    Too many sellers means price competition will erode margins.
    High FBA percentage means Amazon and FBA sellers dominate.
    """

    rule_name = "competition"
    display_name = "Competition Level"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        new_sellers = data.get("new_seller_count", 0)
        fba_sellers = data.get("fba_seller_count", 0)
        total_sellers = data.get("total_offer_count", new_sellers)

        if not isinstance(new_sellers, (int, Decimal)):
            new_sellers = int(new_sellers)  # type: ignore[arg-type]
        if not isinstance(fba_sellers, (int, Decimal)):
            fba_sellers = int(fba_sellers)  # type: ignore[arg-type]

        fba_pct = (
            Decimal(str(fba_sellers)) / Decimal(str(new_sellers)) * 100
            if new_sellers > 0 else Decimal("0")
        )

        # Score: combination of seller count and FBA saturation
        # Ideal: 3-10 sellers, < 70% FBA
        seller_count_score = self._normalize_score(
            actual=Decimal(str(new_sellers)),
            minimum=Decimal(str(config.min_new_sellers)),
            target=Decimal(str(config.target_new_sellers)),
        )

        # Penalty for too many sellers (inverted scale)
        if new_sellers > config.target_new_sellers:
            excess = new_sellers - config.target_new_sellers
            max_excess = max(config.max_new_sellers - config.target_new_sellers, 1)
            over_penalty = min(Decimal(str(excess)) / Decimal(str(max_excess)), Decimal("1"))
            seller_count_score = (Decimal("1") - over_penalty) * seller_count_score

        # FBA saturation score
        fba_score = Decimal("1")
        if fba_pct > config.max_fba_percentage:
            fba_excess = (fba_pct - config.max_fba_percentage) / (Decimal("100") - config.max_fba_percentage)
            fba_score = Decimal("1") - fba_excess

        # Combined score (70% seller count, 30% FBA saturation)
        score = (seller_count_score * Decimal("0.7") + fba_score * Decimal("0.3")).quantize(Decimal("0.0001"))
        passed = new_sellers <= config.max_new_sellers and fba_pct <= config.max_fba_percentage

        if passed:
            summary = (
                f"Healthy competition: {new_sellers} sellers "
                f"({fba_pct:.0f}% FBA)"
            )
        else:
            if new_sellers > config.max_new_sellers:
                summary = f"High competition: {new_sellers} sellers exceeds limit of {config.max_new_sellers}"
            else:
                summary = f"High FBA saturation: {fba_pct:.0f}% FBA exceeds limit of {config.max_fba_percentage:.0f}%"

        details = (
            f"{new_sellers} new-condition sellers, {fba_sellers} FBA sellers "
            f"({fba_pct:.0f}% FBA saturation). "
            f"Ideal range: {config.min_new_sellers}-{config.target_new_sellers} sellers "
            f"with <{config.max_fba_percentage:.0f}% FBA."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.competition_severity,
            weight=config.weights.competition_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.competition_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"{new_sellers} sellers ({fba_pct:.0f}% FBA)",
            threshold_value=f"≤{config.max_new_sellers} sellers, ≤{config.max_fba_percentage:.0f}% FBA",
            target_value=f"{config.target_new_sellers} sellers",
            summary=summary,
            details=details,
            data_quality="Based on latest seller count snapshot",
        )


# ═══════════════════════════════════════════════════════════════
# Buy Box Stability Rule
# ═══════════════════════════════════════════════════════════════


class BuyBoxStabilityRule(BaseSourcingRule):
    """Evaluates Buy Box stability and win rate.

    A stable Buy Box with a high win rate means consistent sales.
    Frequent Buy Box changes indicate price wars or seller churn.
    """

    rule_name = "buy_box_stability"
    display_name = "Buy Box Stability"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        buy_box_win_rate = data.get("buy_box_win_rate", Decimal("50"))
        if isinstance(buy_box_win_rate, (int, float)):
            buy_box_win_rate = Decimal(str(buy_box_win_rate))

        # Buy Box score: higher win rate = better
        score = self._normalize_score(
            actual=buy_box_win_rate,
            minimum=config.min_buy_box_win_rate,
            target=Decimal("95"),
        )
        passed = buy_box_win_rate >= config.min_buy_box_win_rate

        if passed:
            summary = f"Stable Buy Box: ~{buy_box_win_rate:.0f}% win rate (minimum: {config.min_buy_box_win_rate:.0f}%)"
        else:
            summary = f"Unstable Buy Box: {buy_box_win_rate:.0f}% win rate is below {config.min_buy_box_win_rate:.0f}%"

        details = (
            f"Buy Box win rate of {buy_box_win_rate:.0f}% indicates "
            f"{'stable' if passed else 'unstable'} pricing environment. "
            f"Low win rates suggest aggressive repricing or seller churn."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.buy_box_severity,
            weight=config.weights.buy_box_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.buy_box_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"{buy_box_win_rate:.0f}%",
            threshold_value=f"≥{config.min_buy_box_win_rate:.0f}%",
            target_value="95%",
            summary=summary,
            details=details,
            data_quality="Based on Buy Box price history over the analysis window",
        )


# ═══════════════════════════════════════════════════════════════
# Price Stability Rule
# ═══════════════════════════════════════════════════════════════


class PriceStabilityRule(BaseSourcingRule):
    """Evaluates price stability over time.

    Volatile prices make profit forecasting unreliable.
    Stable prices indicate a mature market with rational competition.
    Uses coefficient of variation (CV) as the stability metric.
    """

    rule_name = "price_stability"
    display_name = "Price Stability"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        cv = data.get("price_cv", Decimal("0"))  # coefficient of variation
        if isinstance(cv, (int, float)):
            cv = Decimal(str(cv))

        cv_pct = cv * 100

        # Price stability: lower CV = better (inverted scale)
        # CV of 0% = perfect stability (score 1.0)
        # CV at max threshold = score 0.5
        # CV above max = score 0
        if cv_pct <= Decimal("0"):
            score = Decimal("1.0")
        elif cv_pct >= config.max_price_volatility:
            score = Decimal("0")
        else:
            score = (Decimal("1") - cv_pct / config.max_price_volatility).quantize(Decimal("0.0001"))

        passed = cv_pct <= config.max_price_volatility

        if passed:
            summary = f"Stable pricing: CV of {cv_pct:.1f}% (threshold: {config.max_price_volatility:.0f}%)"
        else:
            summary = f"Volatile pricing: CV of {cv_pct:.1f}% exceeds {config.max_price_volatility:.0f}%"

        details = (
            f"Coefficient of Variation (CV) = {cv_pct:.1f}%. "
            f"CV measures price dispersion relative to the mean. "
            f"Lower values indicate more stable, predictable prices. "
            f"CV < {config.max_price_volatility:.0f}% is considered stable."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.price_stability_severity,
            weight=config.weights.price_stability_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.price_stability_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"{cv_pct:.1f}% CV",
            threshold_value=f"≤{config.max_price_volatility:.0f}% CV",
            target_value="0% CV",
            summary=summary,
            details=details,
            data_quality="Calculated from Amazon price history over the analysis window",
        )


# ═══════════════════════════════════════════════════════════════
# Inventory Availability Rule
# ═══════════════════════════════════════════════════════════════


class InventoryAvailabilityRule(BaseSourcingRule):
    """Evaluates whether sufficient inventory is available.

    Products with low stock or long restock times are risky.
    Adequate inventory ensures consistent sales and ranking.
    """

    rule_name = "inventory_availability"
    display_name = "Inventory Availability"

    def evaluate(
        self,
        config: SourcingConfig,
        data: dict[str, object],
    ) -> RuleResult:
        days_of_stock = data.get("days_of_stock", 0)
        quantity_available = data.get("quantity_available", 0)

        if not isinstance(days_of_stock, (int, Decimal)):
            days_of_stock = int(days_of_stock)  # type: ignore[arg-type]
        if not isinstance(quantity_available, (int, Decimal)):
            quantity_available = int(quantity_available)  # type: ignore[arg-type]

        days_val = Decimal(str(days_of_stock))
        target_days = Decimal("90")

        score = self._normalize_score(
            actual=days_val,
            minimum=Decimal(str(config.min_days_of_stock)),
            target=target_days,
        )
        passed = days_of_stock >= config.min_days_of_stock

        if passed:
            if days_of_stock >= 90:
                summary = f"Well-stocked: ~{days_of_stock} days of inventory ({quantity_available} units available)"
            else:
                summary = f"Adequate stock: ~{days_of_stock} days (minimum: {config.min_days_of_stock})"
        else:
            summary = f"Low stock: ~{days_of_stock} days is below minimum of {config.min_days_of_stock}"

        details = (
            f"{quantity_available} units available, estimated {days_of_stock} days of stock "
            f"at current sales rate. "
            f"Target is {target_days:.0f} days of stock for a perfect score."
        )

        return RuleResult(
            rule_name=self.rule_name,
            display_name=self.display_name,
            severity=config.inventory_severity,
            weight=config.weights.inventory_weight,
            score=score,
            passed=passed,
            is_critical_failure=(config.inventory_severity == RuleSeverity.CRITICAL and not passed),
            actual_value=f"{days_of_stock} days ({quantity_available} units)",
            threshold_value=f"≥{config.min_days_of_stock} days",
            target_value="90 days",
            summary=summary,
            details=details,
            data_quality="Based on latest inventory snapshot and sales estimate",
        )
