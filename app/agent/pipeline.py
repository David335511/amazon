"""Sourcing pipeline — orchestrates the full product evaluation flow.

Pipeline stages:
1. Scan supplier → get product list
2. Retrieve Amazon data → get pricing, sales, competition
3. Calculate profit → use profit engine
4. Score opportunity → use sourcing engine
5. Generate recommendation → use AI reasoning
6. Log decision → record for audit
7. Notify → alert on high-value opportunities

Each stage is independent — failures are isolated and logged.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.agent.logger import DecisionLogger
from app.agent.models import (
    DecisionAction,
    DecisionLog,
    Task,
    TaskStatus,
    TaskType,
)
from app.agent.notifier import Notifier
from app.analytics.repository import AnalyticsRepository
from app.core.logging import get_logger
from app.plugins.manager import PluginManager
from app.sourcing.engine import SourcingEngine
from app.sourcing.models import ProductEvaluation

logger = get_logger(__name__)


class SourcingPipeline:
    """Orchestrates the full product sourcing pipeline.

    Each stage is a separate method that can be run independently.
    The pipeline is stateless — all state is in the database and queue.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        sourcing_engine: SourcingEngine,
        analytics_repo: AnalyticsRepository,
        decision_logger: DecisionLogger,
        notifier: Notifier,
        agent_run_id: str,
    ) -> None:
        self._plugin_manager = plugin_manager
        self._sourcing_engine = sourcing_engine
        self._analytics_repo = analytics_repo
        self._decision_logger = decision_logger
        self._notifier = notifier
        self._agent_run_id = agent_run_id

    # ═══════════════════════════════════════════════════════════════
    # Stage 1: Scan Supplier
    # ═══════════════════════════════════════════════════════════════

    async def scan_supplier(
        self,
        supplier_code: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """Scan a supplier for products.

        Args:
            supplier_code: Supplier code (e.g., 'walmart').
            page: Page number.
            page_size: Results per page.

        Returns:
            List of product dicts with supplier_sku, title, price, etc.
        """
        try:
            results = await self._plugin_manager.search(
                supplier_code, query="", page=page, page_size=page_size,
            )
            products = []
            for r in results:
                products.append({
                    "supplier_code": supplier_code,
                    "supplier_sku": r.supplier_sku,
                    "title": r.title,
                    "upc": r.upc,
                    "brand": r.brand,
                    "price": float(r.price) if r.price else 0,
                    "currency": r.currency,
                    "in_stock": r.in_stock,
                    "image_url": r.image_url,
                    "category": r.category,
                })
            logger.info(
                "Scanned supplier %s (page %d): %d products",
                supplier_code, page, len(products),
            )
            return products
        except Exception as exc:
            logger.error("Failed to scan supplier %s: %s", supplier_code, exc)
            raise

    # ═══════════════════════════════════════════════════════════════
    # Stage 2: Retrieve Amazon Data
    # ═══════════════════════════════════════════════════════════════

    async def retrieve_amazon_data(
        self,
        asin: str,
    ) -> dict[str, Any] | None:
        """Retrieve Amazon data for a product.

        Args:
            asin: Amazon ASIN.

        Returns:
            Product data dict or None if not found.
        """
        try:
            product = await self._analytics_repo.get_product_by_asin(asin)
            if product is None:
                logger.debug("Product %s not found in database", asin)
                return None

            # Gather all analytics data
            data: dict[str, Any] = {
                "product_id": str(product.id),
                "asin": product.asin,
                "title": product.title,
                "amazon_price": float(product.price) if product.price else 0,
            }

            # Latest Amazon price
            latest_price = await self._analytics_repo.get_latest_amazon_price(
                product.id, is_buy_box=False,
            )
            if latest_price:
                data["amazon_price"] = float(latest_price.price)

            # Latest Buy Box
            latest_bb = await self._analytics_repo.get_latest_amazon_price(
                product.id, is_buy_box=True,
            )
            if latest_bb:
                data["buy_box_price"] = float(latest_bb.price)

            # Latest seller counts
            sellers = await self._analytics_repo.get_latest_seller_count(product.id)
            if sellers:
                data["new_seller_count"] = sellers.new_seller_count
                data["fba_seller_count"] = sellers.fba_seller_count

            # Latest sales estimate
            sales = await self._analytics_repo.get_latest_sales_estimate(product.id)
            if sales:
                data["estimated_monthly_sales"] = sales.estimated_monthly_sales
                data["estimated_daily_sales"] = float(sales.estimated_daily_sales)
                data["sales_rank"] = sales.sales_rank

            # Latest fees
            fees = await self._analytics_repo.get_latest_fees(product.id)
            if fees:
                data["referral_fee"] = float(fees.referral_fee)
                data["fulfillment_fee"] = float(fees.fulfillment_fee)
                data["total_fees"] = float(fees.total_fees)

            # Latest inventory
            inv = await self._analytics_repo.get_latest_inventory(product.id)
            if inv:
                data["quantity_available"] = inv.quantity_available
                data["days_of_stock"] = (
                    int(inv.quantity_available / float(sales.estimated_daily_sales))
                    if sales and sales.estimated_daily_sales > 0 and inv.quantity_available > 0
                    else 0
                )

            return data

        except Exception as exc:
            logger.error("Failed to retrieve Amazon data for %s: %s", asin, exc)
            return None

    # ═══════════════════════════════════════════════════════════════
    # Stage 3: Full Pipeline for One Product
    # ═══════════════════════════════════════════════════════════════

    async def run_full_pipeline(
        self,
        supplier_code: str,
        supplier_sku: str,
        product_title: str,
        supplier_price: float,
        asin: str | None = None,
        upc: str | None = None,
    ) -> DecisionLog:
        """Run the full sourcing pipeline for a single product.

        This is the core method that:
        1. Retrieves Amazon data (by ASIN or UPC)
        2. Evaluates using the sourcing engine
        3. Logs the decision
        4. Notifies if high-value

        Args:
            supplier_code: Supplier code.
            supplier_sku: Supplier's SKU.
            product_title: Product title.
            supplier_price: Supplier price.
            asin: Amazon ASIN (if known).
            upc: UPC barcode (for matching).

        Returns:
            DecisionLog with the result.
        """
        start_time = time.monotonic()
        decision = DecisionLog(
            id=str(uuid.uuid4()),
            agent_run_id=self._agent_run_id,
            supplier_code=supplier_code,
            supplier_sku=supplier_sku,
            product_title=product_title,
            supplier_price=supplier_price,
            action=DecisionAction.SKIP,
        )

        try:
            # Step 1: Find or create product in database
            product = None
            if asin:
                product = await self._analytics_repo.get_product_by_asin(asin)
            if product is None and upc:
                product = await self._analytics_repo.find_by_upc(upc)

            if product is None:
                decision.action = DecisionAction.SKIP
                decision.explanation = f"Product not found in database (ASIN: {asin}, UPC: {upc})"
                await self._decision_logger.log(decision)
                return decision

            # Step 2: Evaluate using sourcing engine
            evaluation = await self._sourcing_engine.evaluate_product(
                product.id, days=90,
            )

            if evaluation is None:
                decision.action = DecisionAction.ERROR
                decision.error = "Evaluation returned None"
                await self._decision_logger.log(decision)
                return decision

            # Step 3: Populate decision from evaluation
            score = evaluation.opportunity_score
            decision.asin = product.asin
            decision.product_title = product.title
            decision.opportunity_score = float(score.total_score)
            decision.confidence = evaluation.confidence.value
            decision.risk_level = evaluation.risk_level.value
            decision.strengths = evaluation.strengths
            decision.weaknesses = evaluation.weaknesses
            decision.data_points_used = evaluation.data_points_used

            # Extract metrics from rule results
            for rule in score.rule_results:
                if rule.rule_name == "minimum_roi" and rule.actual_value:
                    try:
                        decision.roi_percentage = float(rule.actual_value.replace("%", ""))
                    except (ValueError, AttributeError):
                        pass
                elif rule.rule_name == "minimum_profit" and rule.actual_value:
                    try:
                        decision.net_profit = float(rule.actual_value.replace("$", ""))
                    except (ValueError, AttributeError):
                        pass
                elif rule.rule_name == "minimum_sales" and rule.actual_value:
                    try:
                        val = rule.actual_value.split("/")[0].replace(",", "")
                        decision.monthly_sales = int(float(val))
                    except (ValueError, AttributeError, IndexError):
                        pass

            decision.amazon_price = float(product.price) if product.price else 0

            # Step 4: Determine action
            if score.is_viable and float(score.total_score) >= 70:
                decision.action = DecisionAction.BUY
            elif score.is_viable:
                decision.action = DecisionAction.WATCH
            else:
                decision.action = DecisionAction.AVOID

            # Step 5: Use AI recommendation if available
            if evaluation.ai_recommendation:
                decision.recommendation = evaluation.ai_recommendation.recommendation.value
                decision.risks = evaluation.ai_recommendation.risks
                decision.explanation = evaluation.ai_recommendation.explanation
            else:
                decision.explanation = evaluation.summary

            # Step 6: Log decision
            decision.pipeline_duration_ms = (time.monotonic() - start_time) * 1000
            await self._decision_logger.log(decision)

            # Step 7: Notify if high-value
            if decision.action == DecisionAction.BUY:
                await self._notifier.notify_opportunity(decision)
            elif decision.action == DecisionAction.WATCH:
                await self._notifier.notify_watch(decision)

            logger.info(
                "Pipeline complete for %s (%s): %s (score: %.1f, ROI: %.1f%%)",
                product_title, product.asin,
                decision.action.value,
                decision.opportunity_score or 0,
                decision.roi_percentage or 0,
            )

        except Exception as exc:
            decision.action = DecisionAction.ERROR
            decision.error = str(exc)
            decision.pipeline_duration_ms = (time.monotonic() - start_time) * 1000
            await self._decision_logger.log(decision)
            logger.error("Pipeline failed for %s: %s", product_title, exc)

        return decision
