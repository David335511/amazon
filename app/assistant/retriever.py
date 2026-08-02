"""Retriever — retrieves data from the platform database for the AI assistant.

Design decisions:
- Every retrieval function returns structured data + a human-readable summary.
- Retrieval happens BEFORE any LLM call (RAG pattern).
- Retrieved data is included in the response for transparency.
- All retrievals are read-only — no mutations.
- Failures are isolated — one failed retrieval doesn't block others.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import AnalyticsRepository
from app.assistant.models import DataSource, RetrievedContext
from app.core.logging import get_logger
from app.domain.models.product import Product
from app.domain.models.sourcing import (
    AmazonPrice,
    HistoricalFee,
    HistoricalInventory,
    ProductPrice,
    ProfitCalculation,
    SalesEstimate,
    SellerCount,
    Supplier,
    SupplierProduct,
)
from app.plugins.manager import PluginManager

logger = get_logger(__name__)


class AssistantRetriever:
    """Retrieves data from the platform database for the AI assistant.

    Each method returns a RetrievedContext with the data and a summary.
    """

    def __init__(
        self,
        db: AsyncSession,
        analytics_repo: AnalyticsRepository | None = None,
        plugin_manager: PluginManager | None = None,
    ) -> None:
        self._db = db
        self._analytics = analytics_repo or AnalyticsRepository(db)
        self._plugin_manager = plugin_manager

    # ═══════════════════════════════════════════════════════════════
    # Product Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def get_product(self, product_id: UUID | None = None, asin: str | None = None) -> RetrievedContext | None:
        """Get product details."""
        if product_id:
            product = await self._analytics.get(product_id)
        elif asin:
            product = await self._analytics.get_product_by_asin(asin)
        else:
            return None
        if product is None:
            return None

        return RetrievedContext(
            source=DataSource.PRODUCT_DATABASE,
            summary=f"Product: {product.title} (ASIN: {product.asin})",
            data={
                "id": str(product.id),
                "asin": product.asin,
                "title": product.title,
                "price": float(product.price) if product.price else 0,
                "upc": product.upc,
                "is_active": product.is_active,
                "is_fba": product.is_amazon_fba,
            },
            record_count=1,
        )

    # ═══════════════════════════════════════════════════════════════
    # Profit Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def get_profit_data(self, product_id: UUID) -> list[RetrievedContext]:
        """Get all data needed for profit analysis."""
        contexts: list[RetrievedContext] = []

        # Latest Amazon price
        latest_price = await self._analytics.get_latest_amazon_price(product_id, is_buy_box=False)
        if latest_price:
            contexts.append(RetrievedContext(
                source=DataSource.AMAZON_PRICES,
                summary=f"Current Amazon price: ${latest_price.price:.2f}",
                data={"price": float(latest_price.price), "currency": latest_price.currency},
                record_count=1,
            ))

        # Latest Buy Box
        latest_bb = await self._analytics.get_latest_amazon_price(product_id, is_buy_box=True)
        if latest_bb:
            contexts.append(RetrievedContext(
                source=DataSource.AMAZON_PRICES,
                summary=f"Current Buy Box price: ${latest_bb.price:.2f}",
                data={"buy_box_price": float(latest_bb.price)},
                record_count=1,
            ))

        # Supplier prices
        supplier_prices = await self._analytics.get_latest_supplier_prices(product_id)
        if supplier_prices:
            prices = [float(sp.price) for sp in supplier_prices]
            contexts.append(RetrievedContext(
                source=DataSource.SUPPLIER_PRICES,
                summary=f"{len(supplier_prices)} supplier(s), lowest: ${min(prices):.2f}, avg: ${sum(prices)/len(prices):.2f}",
                data={
                    "lowest_price": min(prices),
                    "average_price": sum(prices) / len(prices),
                    "supplier_count": len(supplier_prices),
                },
                record_count=len(supplier_prices),
            ))

        # Latest fees
        fees = await self._analytics.get_latest_fees(product_id)
        if fees:
            contexts.append(RetrievedContext(
                source=DataSource.HISTORICAL_FEES,
                summary=f"Total fees: ${fees.total_fees:.2f} (referral: ${fees.referral_fee:.2f}, fulfillment: ${fees.fulfillment_fee:.2f})",
                data={
                    "referral_fee": float(fees.referral_fee),
                    "fulfillment_fee": float(fees.fulfillment_fee),
                    "storage_fee": float(fees.storage_fee),
                    "total_fees": float(fees.total_fees),
                },
                record_count=1,
            ))

        # Latest profit calculation
        profit = await self._analytics.get_latest_profit(product_id)
        if profit:
            contexts.append(RetrievedContext(
                source=DataSource.PROFIT_CALCULATIONS,
                summary=f"Net profit: ${profit.net_profit:.2f}/unit, ROI: {profit.roi_percentage:.1f}%, Margin: {profit.margin_percentage:.1f}%",
                data={
                    "net_profit": float(profit.net_profit),
                    "gross_profit": float(profit.gross_profit),
                    "roi_percentage": float(profit.roi_percentage),
                    "margin_percentage": float(profit.margin_percentage),
                    "total_cost": float(profit.total_cost),
                },
                record_count=1,
            ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Sales & Demand Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def get_sales_data(self, product_id: UUID, days: int = 90) -> list[RetrievedContext]:
        """Get sales and demand data."""
        contexts: list[RetrievedContext] = []

        # Latest sales estimate
        sales = await self._analytics.get_latest_sales_estimate(product_id)
        if sales:
            contexts.append(RetrievedContext(
                source=DataSource.SALES_ESTIMATES,
                summary=f"~{sales.estimated_monthly_sales:,}/month ({sales.estimated_daily_sales:.1f}/day), rank: #{sales.sales_rank}",
                data={
                    "monthly_sales": sales.estimated_monthly_sales,
                    "daily_sales": float(sales.estimated_daily_sales),
                    "monthly_revenue": float(sales.estimated_monthly_revenue),
                    "sales_rank": sales.sales_rank,
                },
                record_count=1,
            ))

        # Sales history
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        history = await self._analytics.get_bsr_series(product_id, since=since, limit=30)
        if history:
            contexts.append(RetrievedContext(
                source=DataSource.SALES_ESTIMATES,
                summary=f"{len(history)} sales data points over {days} days",
                data={"data_points": len(history)},
                record_count=len(history),
            ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Competition Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def get_competition_data(self, product_id: UUID) -> list[RetrievedContext]:
        """Get competition data."""
        contexts: list[RetrievedContext] = []

        sellers = await self._analytics.get_latest_seller_count(product_id)
        if sellers:
            contexts.append(RetrievedContext(
                source=DataSource.SELLER_COUNTS,
                summary=f"{sellers.new_seller_count} new sellers, {sellers.fba_seller_count} FBA ({sellers.fba_seller_count/max(sellers.new_seller_count,1)*100:.0f}% FBA)",
                data={
                    "new_sellers": sellers.new_seller_count,
                    "used_sellers": sellers.used_seller_count,
                    "fba_sellers": sellers.fba_seller_count,
                },
                record_count=1,
            ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Inventory Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def get_inventory_data(self, product_id: UUID) -> list[RetrievedContext]:
        """Get inventory data."""
        contexts: list[RetrievedContext] = []

        inv = await self._analytics.get_latest_inventory(product_id)
        if inv:
            sales = await self._analytics.get_latest_sales_estimate(product_id)
            daily_sales = float(sales.estimated_daily_sales) if sales else 0
            days_of_stock = int(inv.quantity_available / daily_sales) if daily_sales > 0 and inv.quantity_available > 0 else 0

            contexts.append(RetrievedContext(
                source=DataSource.HISTORICAL_INVENTORY,
                summary=f"{inv.quantity_available} available ({inv.quantity_on_hand} on hand, {inv.quantity_reserved} reserved), ~{days_of_stock} days of stock",
                data={
                    "on_hand": inv.quantity_on_hand,
                    "reserved": inv.quantity_reserved,
                    "inbound": inv.quantity_inbound,
                    "available": inv.quantity_available,
                    "days_of_stock": days_of_stock,
                    "daily_sales_rate": daily_sales,
                },
                record_count=1,
            ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Supplier Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def get_suppliers_for_product(self, product_id: UUID) -> list[RetrievedContext]:
        """Get suppliers for a product."""
        contexts: list[RetrievedContext] = []

        stmt = (
            select(SupplierProduct, Supplier)
            .join(Supplier, SupplierProduct.supplier_id == Supplier.id)
            .where(SupplierProduct.product_id == product_id)
            .where(SupplierProduct.is_active == True)  # noqa: E712
        )
        result = await self._db.execute(stmt)
        rows = result.fetchall()

        if rows:
            suppliers_data = []
            for sp, s in rows:
                suppliers_data.append({
                    "code": s.name.lower().replace(" ", "_"),
                    "name": s.name,
                    "sku": sp.supplier_sku,
                    "price": float(sp.supplier_price),
                    "moq": sp.moq,
                    "lead_time": sp.lead_time_days,
                    "rating": float(s.rating) if s.rating else None,
                })

            contexts.append(RetrievedContext(
                source=DataSource.SUPPLIER_DATABASE,
                summary=f"{len(suppliers_data)} supplier(s) for this product",
                data={"suppliers": suppliers_data},
                record_count=len(suppliers_data),
            ))

        return contexts

    async def get_all_suppliers(self) -> list[RetrievedContext]:
        """Get all suppliers."""
        contexts: list[RetrievedContext] = []

        stmt = select(Supplier).where(Supplier.is_active == True)  # noqa: E712
        result = await self._db.execute(stmt)
        suppliers = result.scalars().all()

        if suppliers:
            contexts.append(RetrievedContext(
                source=DataSource.SUPPLIER_DATABASE,
                summary=f"{len(suppliers)} active suppliers",
                data={
                    "suppliers": [
                        {
                            "code": s.name.lower().replace(" ", "_"),
                            "name": s.name,
                            "rating": float(s.rating) if s.rating else None,
                            "country": s.country,
                        }
                        for s in suppliers
                    ],
                },
                record_count=len(suppliers),
            ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Similar Products Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def find_similar_products(
        self,
        product_id: UUID,
        limit: int = 10,
    ) -> list[RetrievedContext]:
        """Find similar products by category and price range."""
        contexts: list[RetrievedContext] = []

        product = await self._analytics.get(product_id)
        if product is None:
            return contexts

        # Find products in same category with similar price
        if product.category_id:
            price = float(product.price) if product.price else 0
            price_min = price * 0.5
            price_max = price * 2.0

            stmt = (
                select(Product)
                .where(Product.category_id == product.category_id)
                .where(Product.id != product_id)
                .where(Product.is_active == True)  # noqa: E712
                .where(Product.price.between(price_min, price_max))
                .order_by(Product.title)
                .limit(limit)
            )
            result = await self._db.execute(stmt)
            similar = result.scalars().all()

            if similar:
                contexts.append(RetrievedContext(
                    source=DataSource.PRODUCT_DATABASE,
                    summary=f"{len(similar)} similar products in same category with similar price range",
                    data={
                        "similar_products": [
                            {
                                "id": str(p.id),
                                "asin": p.asin,
                                "title": p.title,
                                "price": float(p.price) if p.price else 0,
                            }
                            for p in similar
                        ],
                        "category": str(product.category_id),
                        "price_range": {"min": price_min, "max": price_max},
                    },
                    record_count=len(similar),
                ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Opportunity Summaries
    # ═══════════════════════════════════════════════════════════════

    async def get_recent_opportunities(
        self,
        limit: int = 20,
        days: int = 1,
    ) -> list[RetrievedContext]:
        """Get recent high-scoring opportunities from profit calculations."""
        contexts: list[RetrievedContext] = []

        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        stmt = (
            select(ProfitCalculation, Product)
            .join(Product, ProfitCalculation.product_id == Product.id)
            .where(ProfitCalculation.effective_date >= since)
            .where(ProfitCalculation.net_profit > 0)
            .order_by(desc(ProfitCalculation.roi_percentage))
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        rows = result.fetchall()

        if rows:
            opportunities = []
            for pc, p in rows:
                opportunities.append({
                    "product_id": str(p.id),
                    "asin": p.asin,
                    "title": p.title,
                    "net_profit": float(pc.net_profit),
                    "roi": float(pc.roi_percentage),
                    "margin": float(pc.margin_percentage),
                    "amazon_price": float(pc.amazon_price),
                    "unit_cost": float(pc.unit_cost),
                })

            total_monthly_profit = sum(
                o["net_profit"] * 1000 for o in opportunities[:5]
            )

            contexts.append(RetrievedContext(
                source=DataSource.PROFIT_CALCULATIONS,
                summary=f"{len(opportunities)} profitable products found in the last {days} day(s)",
                data={
                    "opportunities": opportunities,
                    "total_opportunities": len(opportunities),
                    "estimated_monthly_profit_top5": total_monthly_profit,
                },
                record_count=len(opportunities),
            ))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Price History for Trend Analysis
    # ═══════════════════════════════════════════════════════════════

    async def get_price_history(
        self,
        product_id: UUID,
        days: int = 90,
    ) -> list[RetrievedContext]:
        """Get price history for trend analysis."""
        contexts: list[RetrievedContext] = []

        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        prices = await self._analytics.get_amazon_price_series(
            product_id, since=since, limit=100,
        )

        if prices:
            values = [float(p.price) for p in prices]
            contexts.append(RetrievedContext(
                source=DataSource.AMAZON_PRICES,
                summary=f"{len(prices)} price points over {days} days, range: ${min(values):.2f}-${max(values):.2f}",
                data={
                    "data_points": len(prices),
                    "min_price": min(values),
                    "max_price": max(values),
                    "avg_price": sum(values) / len(values),
                    "latest_price": values[0] if values else 0,
                    "earliest_price": values[-1] if values else 0,
                },
                record_count=len(prices),
            ))

        return contexts
