"""Sourcing engine — orchestrates product evaluation, scoring, and ranking.

Design decisions:
- The engine runs all rules against each product and aggregates scores.
- Rules are independent — one rule failure doesn't affect others.
- The Opportunity Score is a weighted average of all rule scores.
- Confidence is derived from data quality and coverage.
- Risk is derived from rule failures and severity.
- Products are ranked by Opportunity Score descending.
- The engine is stateless — all configuration is passed in.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.analytics.repository import AnalyticsRepository
from app.analytics.schemas import HistoricalSummary, TrendDirection
from app.core.logging import get_logger
from app.profit.config import DEFAULT_PROFIT_CONFIG, ProfitConfig
from app.profit.engine import ProfitEngine
from app.profit.models import ProfitInput

# Lazy import for AI reasoning to avoid circular imports
AIReasoningEngine = None

def _get_ai_reasoning():
    global AIReasoningEngine
    if AIReasoningEngine is None:
        from app.ai.reasoning import AIReasoningEngine as _ARE
        AIReasoningEngine = _ARE
    return AIReasoningEngine
from app.sourcing.models import (
    ConfidenceLevel,
    OpportunityScore,
    ProductEvaluation,
    RiskLevel,
    RuleResult,
    RuleSeverity,
    SourcingConfig,
    SourcingResult,
    SourcingWeights,
)
from app.sourcing.rules import (
    BaseSourcingRule,
    BuyBoxStabilityRule,
    CompetitionRule,
    InventoryAvailabilityRule,
    MinimumProfitRule,
    MinimumRoiRule,
    MinimumSalesRule,
    PriceStabilityRule,
)

logger = get_logger(__name__)

# Default rules with their weights
DEFAULT_RULES: list[BaseSourcingRule] = [
    MinimumRoiRule(),
    MinimumProfitRule(),
    MinimumSalesRule(),
    CompetitionRule(),
    BuyBoxStabilityRule(),
    PriceStabilityRule(),
    InventoryAvailabilityRule(),
]

# Minimum data points needed for each confidence level
CONFIDENCE_THRESHOLDS: list[tuple[int, ConfidenceLevel]] = [
    (500, ConfidenceLevel.VERY_HIGH),
    (200, ConfidenceLevel.HIGH),
    (50, ConfidenceLevel.MEDIUM),
    (10, ConfidenceLevel.LOW),
    (0, ConfidenceLevel.VERY_LOW),
]

# Risk thresholds (based on score)
RISK_THRESHOLDS: list[tuple[Decimal, RiskLevel]] = [
    (Decimal("85"), RiskLevel.VERY_LOW),
    (Decimal("70"), RiskLevel.LOW),
    (Decimal("50"), RiskLevel.MEDIUM),
    (Decimal("30"), RiskLevel.HIGH),
    (Decimal("0"), RiskLevel.VERY_HIGH),
]


class SourcingEngine:
    """Orchestrates product sourcing evaluation and ranking.

    Usage:
        engine = SourcingEngine(repository)
        result = await engine.evaluate_products([product_id_1, product_id_2])
        best = result.evaluations[0]
        print(f"Best opportunity: {best.title} (score: {best.opportunity_score.total_score})")
    """

    def __init__(
        self,
        repository: AnalyticsRepository,
        config: SourcingConfig | None = None,
        profit_config: ProfitConfig | None = None,
        rules: list[BaseSourcingRule] | None = None,
        ai_reasoning: AIReasoningEngine | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or SourcingConfig()
        self._profit_engine = ProfitEngine(config=profit_config or DEFAULT_PROFIT_CONFIG)
        self._rules = rules or DEFAULT_RULES
        self._ai_reasoning = ai_reasoning

    # ═══════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════

    async def evaluate_products(
        self,
        product_ids: list[UUID],
        *,
        days: int = 90,
    ) -> SourcingResult:
        """Evaluate multiple products and return ranked results.

        Args:
            product_ids: List of product UUIDs to evaluate.
            days: Analysis window in days for historical data.

        Returns:
            SourcingResult with evaluations sorted by score descending.
        """
        evaluations: list[ProductEvaluation] = []

        for pid in product_ids:
            try:
                evaluation = await self._evaluate_single(pid, days=days)
                evaluations.append(evaluation)
            except Exception as exc:
                logger.warning("Evaluation failed for product %s: %s", pid, exc)

        # Sort by score descending
        evaluations.sort(
            key=lambda e: e.opportunity_score.total_score,
            reverse=True,
        )

        viable = sum(1 for e in evaluations if e.opportunity_score.is_viable)
        non_viable = len(evaluations) - viable

        return SourcingResult(
            evaluations=evaluations,
            total_evaluated=len(evaluations),
            viable_count=viable,
            non_viable_count=non_viable,
            config=self._config,
        )

    async def evaluate_product(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> ProductEvaluation | None:
        """Evaluate a single product.

        Args:
            product_id: Product UUID.
            days: Analysis window in days.

        Returns:
            ProductEvaluation or None if product not found.
        """
        try:
            return await self._evaluate_single(product_id, days=days)
        except Exception as exc:
            logger.error("Evaluation failed for product %s: %s", product_id, exc)
            return None

    # ═══════════════════════════════════════════════════════════════
    # Single Product Evaluation
    # ═══════════════════════════════════════════════════════════════

    async def _evaluate_single(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> ProductEvaluation:
        """Evaluate a single product end-to-end."""
        # Get product
        product = await self._repo.get(product_id)
        if product is None:
            raise ValueError(f"Product {product_id} not found")

        # Gather all data needed for evaluation
        data = await self._gather_data(product_id, days=days)

        # Calculate profit metrics
        profit_data = await self._calculate_profit(data)
        data.update(profit_data)

        # Run all rules
        rule_results = []
        for rule in self._rules:
            result = rule.evaluate(self._config, data)
            rule_results.append(result)

        # Calculate opportunity score
        opportunity = self._calculate_opportunity_score(rule_results)

        # Determine confidence and risk
        total_data_points = data.get("total_data_points", 0)
        confidence = self._determine_confidence(total_data_points)
        risk = self._determine_risk(opportunity.total_score, rule_results)

        # Generate summary, strengths, weaknesses, recommendations
        summary = self._generate_summary(product.title, opportunity, rule_results)
        strengths = self._identify_strengths(rule_results)
        weaknesses = self._identify_weaknesses(rule_results)
        recommendations = self._generate_recommendations(rule_results, data)

        # Generate AI-powered recommendation if available
        ai_recommendation = None
        if self._ai_reasoning is not None:
            try:
                ARE = _get_ai_reasoning()
                ai_data = ARE.build_product_data(evaluation)
                # Merge in raw metrics for richer analysis
                ai_data.update({
                    "amazon_price": str(data.get("amazon_price", "")),
                    "buy_box_price": str(data.get("buy_box_price", "")),
                    "lowest_supplier_price": str(data.get("lowest_supplier_price", "")),
                    "net_profit": str(data.get("net_profit", "")),
                    "gross_profit": str(data.get("gross_profit", "")),
                    "roi_percentage": str(data.get("roi_percentage", "")),
                    "margin_percentage": str(data.get("margin_percentage", "")),
                    "estimated_monthly_sales": str(data.get("estimated_monthly_sales", "")),
                    "estimated_daily_sales": str(data.get("estimated_daily_sales", "")),
                    "sales_rank": str(data.get("sales_rank", "")),
                    "new_seller_count": str(data.get("new_seller_count", "")),
                    "fba_seller_count": str(data.get("fba_seller_count", "")),
                    "total_offer_count": str(data.get("total_offer_count", "")),
                    "referral_fee": str(data.get("referral_fee", "")),
                    "fulfillment_fee": str(data.get("fulfillment_fee", "")),
                    "total_fees": str(data.get("total_fees", "")),
                    "quantity_available": str(data.get("quantity_available", "")),
                    "days_of_stock": str(data.get("days_of_stock", "")),
                    "buy_box_win_rate": str(data.get("buy_box_win_rate", "")),
                    "price_cv": str(data.get("price_cv", "")),
                    "price_count": str(data.get("price_count", 0)),
                })
                ai_recommendation = await self._ai_reasoning.analyze(ai_data)
            except Exception as exc:
                logger.warning("AI reasoning failed for %s: %s", product.asin, exc)

        return ProductEvaluation(
            product_id=product_id,
            asin=product.asin,
            title=product.title,
            opportunity_score=opportunity,
            confidence=confidence,
            risk_level=risk,
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            data_points_used=total_data_points,
            data_quality_note=self._data_quality_note(total_data_points),
            ai_recommendation=ai_recommendation,
        )

    # ═══════════════════════════════════════════════════════════════
    # Data Gathering
    # ═══════════════════════════════════════════════════════════════

    async def _gather_data(
        self,
        product_id: UUID,
        *,
        days: int = 90,
    ) -> dict[str, object]:
        """Gather all data needed for evaluation from the analytics repository.

        Returns a flat dict of all metrics used by the rules.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)

        data: dict[str, object] = {}

        # ── Latest Amazon Price ──────────────────────────────
        latest_price = await self._repo.get_latest_amazon_price(product_id, is_buy_box=False)
        latest_buy_box = await self._repo.get_latest_amazon_price(product_id, is_buy_box=True)
        data["amazon_price"] = latest_price.price if latest_price else Decimal("0")
        data["buy_box_price"] = latest_buy_box.price if latest_buy_box else None

        # ── Latest Supplier Prices ──────────────────────────
        supplier_prices = await self._repo.get_latest_supplier_prices(product_id)
        if supplier_prices:
            prices_list = [sp.price for sp in supplier_prices]
            data["lowest_supplier_price"] = min(prices_list)
            data["average_supplier_price"] = sum(prices_list) / len(prices_list)
            data["supplier_count"] = len(prices_list)
        else:
            data["lowest_supplier_price"] = Decimal("0")
            data["average_supplier_price"] = Decimal("0")
            data["supplier_count"] = 0

        # ── Latest Seller Counts ────────────────────────────
        latest_sellers = await self._repo.get_latest_seller_count(product_id)
        if latest_sellers:
            data["new_seller_count"] = latest_sellers.new_seller_count
            data["used_seller_count"] = latest_sellers.used_seller_count
            data["fba_seller_count"] = latest_sellers.fba_seller_count
            data["total_offer_count"] = (
                latest_sellers.new_seller_count + latest_sellers.used_seller_count
            )
        else:
            data["new_seller_count"] = 0
            data["used_seller_count"] = 0
            data["fba_seller_count"] = 0
            data["total_offer_count"] = 0

        # ── Latest Sales Estimate ───────────────────────────
        latest_sales = await self._repo.get_latest_sales_estimate(product_id)
        if latest_sales:
            data["estimated_monthly_sales"] = latest_sales.estimated_monthly_sales
            data["estimated_daily_sales"] = latest_sales.estimated_daily_sales
            data["sales_rank"] = latest_sales.sales_rank
        else:
            data["estimated_monthly_sales"] = 0
            data["estimated_daily_sales"] = Decimal("0")
            data["sales_rank"] = None

        # ── Latest Fees ────────────────────────────────────
        latest_fees = await self._repo.get_latest_fees(product_id)
        if latest_fees:
            data["referral_fee"] = latest_fees.referral_fee
            data["fulfillment_fee"] = latest_fees.fulfillment_fee
            data["storage_fee"] = latest_fees.storage_fee
            data["total_fees"] = latest_fees.total_fees
        else:
            data["referral_fee"] = Decimal("0")
            data["fulfillment_fee"] = Decimal("0")
            data["storage_fee"] = Decimal("0")
            data["total_fees"] = Decimal("0")

        # ── Latest Inventory ───────────────────────────────
        latest_inv = await self._repo.get_latest_inventory(product_id)
        if latest_inv:
            data["quantity_on_hand"] = latest_inv.quantity_on_hand
            data["quantity_reserved"] = latest_inv.quantity_reserved
            data["quantity_inbound"] = latest_inv.quantity_inbound
            data["quantity_available"] = latest_inv.quantity_available
        else:
            data["quantity_on_hand"] = 0
            data["quantity_reserved"] = 0
            data["quantity_inbound"] = 0
            data["quantity_available"] = 0

        # ── Days of Stock ──────────────────────────────────
        daily_sales = data.get("estimated_daily_sales", Decimal("0"))
        available = data.get("quantity_available", 0)
        if isinstance(daily_sales, Decimal) and daily_sales > 0 and available > 0:
            data["days_of_stock"] = int(Decimal(str(available)) / daily_sales)
        else:
            data["days_of_stock"] = 0

        # ── Price History Summary ──────────────────────────
        try:
            price_summary = await self._repo.compute_summary(
                product_id, "amazon_prices", "price",
                since=since,
            )
            if price_summary:
                data["price_mean"] = price_summary.get("mean", 0)
                data["price_stddev"] = price_summary.get("stddev", 0)
                data["price_min"] = price_summary.get("min", 0)
                data["price_max"] = price_summary.get("max", 0)
                data["price_count"] = price_summary.get("count", 0)

                # Coefficient of variation
                mean_val = float(price_summary.get("mean", 0) or 0)
                stddev_val = float(price_summary.get("stddev", 0) or 0)
                if mean_val > 0:
                    data["price_cv"] = Decimal(str(stddev_val / mean_val))
                else:
                    data["price_cv"] = Decimal("0")
            else:
                data["price_cv"] = Decimal("0")
                data["price_count"] = 0
        except Exception:
            data["price_cv"] = Decimal("0")
            data["price_count"] = 0

        # ── Buy Box Win Rate ───────────────────────────────
        try:
            bb_summary = await self._repo.compute_summary(
                product_id, "amazon_prices", "price",
                since=since,
            )
            # Count buy box vs total price observations
            bb_count = await self._repo.count_data_points(product_id, "amazon_prices")
            # Approximate win rate from buy_box flag
            from app.domain.models.sourcing import AmazonPrice
            from sqlalchemy import select, func as sa_func

            stmt = (
                sa_func.count()
            )
            # Simple approach: use 50% as default if we can't compute
            data["buy_box_win_rate"] = Decimal("50")
            data["price_count"] = bb_count
        except Exception:
            data["buy_box_win_rate"] = Decimal("50")

        # ── Total Data Points ──────────────────────────────
        total_points = 0
        for table in ["amazon_prices", "product_prices", "seller_counts",
                       "historical_fees", "historical_inventory", "sales_estimates"]:
            try:
                count = await self._repo.count_data_points(product_id, table)
                total_points += count
            except Exception:
                pass
        data["total_data_points"] = total_points

        return data

    async def _calculate_profit(
        self,
        data: dict[str, object],
    ) -> dict[str, object]:
        """Calculate profit metrics from gathered data."""
        amazon_price = data.get("amazon_price", Decimal("0"))
        if isinstance(amazon_price, (int, float)):
            amazon_price = Decimal(str(amazon_price))

        unit_cost = data.get("lowest_supplier_price", Decimal("0"))
        if isinstance(unit_cost, (int, float)):
            unit_cost = Decimal(str(unit_cost))

        if amazon_price <= 0 or unit_cost <= 0:
            return {
                "net_profit": Decimal("0"),
                "gross_profit": Decimal("0"),
                "roi_percentage": Decimal("0"),
                "margin_percentage": Decimal("0"),
            }

        # Calculate using profit engine
        result = self._profit_engine.calculate(
            ProfitInput(
                amazon_price=amazon_price,
                supplier_price=unit_cost,
                shipping_cost=Decimal("0"),
                fba_fulfillment_fee=data.get("fulfillment_fee", Decimal("0")),
                referral_fee_percent=None,
                quantity=1,
            ),
        )

        return {
            "net_profit": result.net_profit_per_unit,
            "gross_profit": result.gross_profit,
            "roi_percentage": result.roi_percentage,
            "margin_percentage": result.margin_percentage,
        }

    # ═══════════════════════════════════════════════════════════════
    # Scoring
    # ═══════════════════════════════════════════════════════════════

    def _calculate_opportunity_score(
        self,
        rule_results: list[RuleResult],
    ) -> OpportunityScore:
        """Calculate the overall opportunity score from rule results.

        Formula:
            weighted_score = Σ(rule_score_i * weight_i) / Σ(weight_i)
            total_score = weighted_score * 100

        If any critical rule fails, the product is marked non-viable.
        """
        total_weighted = Decimal("0")
        total_weight = Decimal("0")
        critical_failures = 0

        for result in rule_results:
            total_weighted += result.score * result.weight
            total_weight += result.weight
            if result.is_critical_failure:
                critical_failures += 1

        weighted_score = (
            total_weighted / total_weight
            if total_weight > 0
            else Decimal("0")
        )
        total_score = (weighted_score * 100).quantize(Decimal("0.01"))

        is_viable = (
            critical_failures < self._config.critical_rule_fail_threshold
            and total_score >= self._config.minimum_opportunity_score
        )

        return OpportunityScore(
            total_score=total_score,
            weighted_score=weighted_score,
            rule_results=rule_results,
            critical_failures=critical_failures,
            is_viable=is_viable,
        )

    # ═══════════════════════════════════════════════════════════════
    # Confidence & Risk
    # ═══════════════════════════════════════════════════════════════

    def _determine_confidence(
        self,
        total_data_points: int,
    ) -> ConfidenceLevel:
        """Determine confidence level based on data quantity."""
        for threshold, level in CONFIDENCE_THRESHOLDS:
            if total_data_points >= threshold:
                return level
        return ConfidenceLevel.VERY_LOW

    def _determine_risk(
        self,
        total_score: Decimal,
        rule_results: list[RuleResult],
    ) -> RiskLevel:
        """Determine risk level from score and rule failures.

        Risk is primarily based on the opportunity score, but is
        elevated if there are critical or major rule failures.
        """
        # Base risk from score
        for threshold, level in RISK_THRESHOLDS:
            if total_score >= threshold:
                base_risk = level
                break
        else:
            base_risk = RiskLevel.VERY_HIGH

        # Elevate risk for failures
        critical_fails = sum(
            1 for r in rule_results
            if r.is_critical_failure
        )
        major_fails = sum(
            1 for r in rule_results
            if r.severity == RuleSeverity.MAJOR and not r.passed
        )

        if critical_fails > 0:
            return RiskLevel.VERY_HIGH
        if major_fails >= 2:
            return RiskLevel.HIGH
        if major_fails == 1:
            # Elevate one level
            risk_order = [
                RiskLevel.VERY_LOW, RiskLevel.LOW, RiskLevel.MEDIUM,
                RiskLevel.HIGH, RiskLevel.VERY_HIGH,
            ]
            idx = risk_order.index(base_risk)
            return risk_order[min(idx + 1, len(risk_order) - 1)]

        return base_risk

    # ═══════════════════════════════════════════════════════════════
    # Summary Generation
    # ═══════════════════════════════════════════════════════════════

    def _generate_summary(
        self,
        title: str,
        opportunity: OpportunityScore,
        rule_results: list[RuleResult],
    ) -> str:
        """Generate a one-paragraph evaluation summary."""
        score = opportunity.total_score
        viable = opportunity.is_viable

        if not viable:
            return (
                f"\"{title}\" scored {score:.1f}/100 and is not currently viable. "
                f"{opportunity.critical_failures} critical rule(s) failed. "
                f"Review the weaknesses below for specific issues to address."
            )

        if score >= 80:
            return (
                f"\"{title}\" is a strong sourcing opportunity with a score of {score:.1f}/100. "
                f"Strong performance across most metrics. "
                f"Consider adding this product to your watchlist."
            )
        if score >= 60:
            return (
                f"\"{title}\" is a viable opportunity scoring {score:.1f}/100. "
                f"Some areas need monitoring, but overall metrics are solid. "
                f"Review the recommendations below for optimization opportunities."
            )

        return (
            f"\"{title}\" scores {score:.1f}/100 — marginal opportunity. "
            f"It meets minimum criteria but has significant room for improvement. "
            f"Consider only if you can address the specific weaknesses noted."
        )

    def _identify_strengths(
        self,
        rule_results: list[RuleResult],
    ) -> list[str]:
        """Identify key strengths from rule results."""
        strengths = []
        for result in rule_results:
            if result.score >= Decimal("0.8"):
                strengths.append(f"{result.display_name}: {result.summary}")
        return strengths[:5]  # Top 5 strengths

    def _identify_weaknesses(
        self,
        rule_results: list[RuleResult],
    ) -> list[str]:
        """Identify key weaknesses from rule results."""
        weaknesses = []
        for result in rule_results:
            if result.score < Decimal("0.5"):
                weaknesses.append(f"{result.display_name}: {result.summary}")
        return weaknesses[:5]  # Top 5 weaknesses

    def _generate_recommendations(
        self,
        rule_results: list[RuleResult],
        data: dict[str, object],
    ) -> list[str]:
        """Generate actionable recommendations based on evaluation."""
        recommendations = []

        for result in rule_results:
            if result.passed:
                continue

            if result.rule_name == "minimum_roi":
                recommendations.append(
                    f"Improve ROI by negotiating better supplier pricing "
                    f"or finding alternative suppliers. Current ROI: {result.actual_value}"
                )
            elif result.rule_name == "minimum_profit":
                recommendations.append(
                    f"Increase profit margin by reducing costs or "
                    f"differentiating to command a higher price. "
                    f"Current profit: {result.actual_value}"
                )
            elif result.rule_name == "minimum_sales":
                recommendations.append(
                    f"Low sales volume ({result.actual_value}). "
                    f"Consider if this is seasonal or if demand can be "
                    f"increased through better listing optimization."
                )
            elif result.rule_name == "competition":
                recommendations.append(
                    f"High competition ({result.actual_value}). "
                    f"Differentiate through bundling, better listings, "
                    f"or targeting a niche within this category."
                )
            elif result.rule_name == "buy_box_stability":
                recommendations.append(
                    f"Unstable Buy Box ({result.actual_value}). "
                    f"Monitor repricing strategies and consider "
                    f"automated repricing tools."
                )
            elif result.rule_name == "price_stability":
                recommendations.append(
                    f"Volatile pricing ({result.actual_value}). "
                    f"Price fluctuations make profit forecasting unreliable. "
                    f"Consider shorter inventory cycles."
                )
            elif result.rule_name == "inventory_availability":
                recommendations.append(
                    f"Insufficient inventory ({result.actual_value}). "
                    f"Secure reliable supplier with shorter lead times "
                    f"or increase order quantity."
                )

        return recommendations

    @staticmethod
    def _data_quality_note(total_data_points: int) -> str | None:
        """Generate a data quality note based on data quantity."""
        if total_data_points >= 500:
            return "Excellent data coverage — evaluation is based on extensive historical data"
        if total_data_points >= 100:
            return "Good data coverage — evaluation is based on adequate historical data"
        if total_data_points >= 20:
            return "Moderate data coverage — some metrics may be less reliable"
        if total_data_points > 0:
            return "Limited data — evaluation should be treated as preliminary"
        return "No historical data available — evaluation is based on current snapshot only"
