"""Tests for the demo supplier plugin + sourcing seed data.

Verifies that the offline `demo` supplier returns the curated catalog and
that seeding matching products + analytics produces the intended spread of
sourcing decisions (BUY / WATCH / WATCH / AVOID) through the real engine.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import AnalyticsRepository
from app.domain.demo_seed import seed_sourcing_demo
from app.domain.models.product import Product
from app.plugins.suppliers.demo import DEMO_CATALOG, DemoPlugin
from app.sourcing.engine import SourcingEngine


async def _decision_action(db: AsyncSession, asin: str) -> str:
    """Map a product's evaluation to the same BUY/WATCH/AVOID the pipeline uses."""
    result = await db.execute(select(Product).where(Product.asin == asin))
    product = result.scalar_one()
    engine = SourcingEngine(AnalyticsRepository(db))
    evaluation = await engine.evaluate_product(product.id, days=90)
    assert evaluation is not None, f"evaluation missing for {asin}"
    score = float(evaluation.opportunity_score.total_score)
    if evaluation.opportunity_score.is_viable and score >= 70:
        return "BUY"
    if evaluation.opportunity_score.is_viable:
        return "WATCH"
    return "AVOID"


# ── Plugin ─────────────────────────────────────────────────────────

async def test_demo_plugin_search_returns_catalog() -> None:
    plugin = DemoPlugin()
    results = await plugin.search("", page=1, page_size=20)
    assert len(results) == len(DEMO_CATALOG)
    assert {r.supplier_sku for r in results} == {i["supplier_sku"] for i in DEMO_CATALOG}
    assert all(r.price > 0 for r in results)


async def test_demo_plugin_search_filters_by_query() -> None:
    plugin = DemoPlugin()
    results = await plugin.search("earbuds")
    assert len(results) == 1
    assert results[0].supplier_sku == "DEMO-EARBUDS"


async def test_demo_plugin_lookup_unknown_sku_returns_none() -> None:
    plugin = DemoPlugin()
    assert await plugin.lookup("DOES-NOT-EXIST") is None


# ── Seed + decisions ───────────────────────────────────────────────

async def test_seed_creates_all_products(db_session: AsyncSession) -> None:
    summary = await seed_sourcing_demo(db_session)
    assert summary["products_created"] == len(DEMO_CATALOG)
    for item in DEMO_CATALOG:
        result = await db_session.execute(
            select(Product).where(Product.asin == item["asin"])
        )
        assert result.scalar_one_or_none() is not None


async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    await seed_sourcing_demo(db_session)
    second = await seed_sourcing_demo(db_session)
    assert second["products_created"] == 0
    assert second["analytics_written"] == 0


async def test_seed_produces_buy_watch_avoid_spread(db_session: AsyncSession) -> None:
    await seed_sourcing_demo(db_session)
    expected = {
        "B0DEMO0001": "BUY",
        "B0DEMO0002": "WATCH",
        "B0DEMO0003": "AVOID",
        "B0DEMO0004": "WATCH",
    }
    for asin, want in expected.items():
        action = await _decision_action(db_session, asin)
        assert action == want, f"{asin}: expected {want}, got {action}"
