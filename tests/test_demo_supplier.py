"""Tests for the demo supplier plugin + sourcing seed data.

Verifies that the offline `demo` supplier returns the curated catalog and
that seeding matching products + analytics produces the intended spread of
sourcing decisions (BUY / WATCH / WATCH / AVOID) through the real engine.
"""

from __future__ import annotations

from collections import Counter
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.pipeline import SourcingPipeline
from app.analytics.repository import AnalyticsRepository
from app.domain.demo_seed import seed_sourcing_demo
from app.domain.models.product import Product
from app.plugins.suppliers.demo import (
    DEFAULT_DEMO_SIZE,
    DEMO_CATALOG,
    DemoPlugin,
    build_demo_catalog,
)
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
    assert len(results) == 20  # paginated
    # the hand-curated products always appear first
    curated_skus = {i["supplier_sku"] for i in DEMO_CATALOG}
    assert curated_skus <= {r.supplier_sku for r in results}
    assert all(r.price > 0 for r in results)
    # a large page exposes the generated catalog
    big = await plugin.search("", page=1, page_size=DEFAULT_DEMO_SIZE)
    assert len(big) == DEFAULT_DEMO_SIZE


async def test_demo_plugin_search_filters_by_query() -> None:
    plugin = DemoPlugin()
    results = await plugin.search("anker")
    assert len(results) == 1
    assert results[0].supplier_sku == "DEMO-ANK-PC10000"


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


# ── End-to-end pipeline (runs the real run_full_pipeline) ──────────

async def test_full_pipeline_produces_decisions(db_session: AsyncSession) -> None:
    """The real sourcing pipeline (scan→match→evaluate→log) yields decisions.

    Guards against regressions like the missing AnalyticsRepository.find_by_upc
    that turned every pipeline decision into an ERROR.
    """
    await seed_sourcing_demo(db_session)
    repo = AnalyticsRepository(db_session)
    pipeline = SourcingPipeline(
        plugin_manager=AsyncMock(),
        sourcing_engine=SourcingEngine(repo),
        analytics_repo=repo,
        decision_logger=AsyncMock(),
        notifier=AsyncMock(),
        agent_run_id="test",
    )

    expected = {
        "DEMO-ANK-PC10000": "BUY",
        "DEMO-EARBUDS": "WATCH",
        "DEMO-USBC": "WATCH",
        "DEMO-CASE": "AVOID",
    }
    for item in DEMO_CATALOG:
        decision = await pipeline.run_full_pipeline(
            supplier_code="demo",
            supplier_sku=item["supplier_sku"],
            product_title=item["title"],
            supplier_price=float(item["price"]),
            asin=None,
            upc=item["upc"],
        )
        assert decision.error is None, f"{item['supplier_sku']}: {decision.error}"
        assert decision.action.value == expected[item["supplier_sku"]], (
            f"{item['supplier_sku']}: got {decision.action.value}"
        )


# ── Large deterministic catalog generator ───────────────────────────

async def test_build_catalog_is_deterministic_and_large() -> None:
    catalog = build_demo_catalog()
    assert len(catalog) == DEFAULT_DEMO_SIZE == 500
    assert len({i["asin"] for i in catalog}) == 500
    assert len({i["upc"] for i in catalog}) == 500
    # curated products are always the first entries
    assert catalog[0]["supplier_sku"] == DEMO_CATALOG[0]["supplier_sku"]
    # fully reproducible
    assert build_demo_catalog() == catalog
    # categories span many markets
    cats = {i["category"] for i in catalog}
    assert len(cats) >= 10


async def test_seed_large_set_and_idempotent(db_session: AsyncSession) -> None:
    first = await seed_sourcing_demo(db_session, count=60)
    assert first["products_created"] == 60
    assert first["products_seeded"] == 60
    assert first["analytics_written"] == 60

    second = await seed_sourcing_demo(db_session, count=60)
    assert second["products_created"] == 0
    assert second["analytics_written"] == 0


async def test_seed_small_count_uses_curated_only(db_session: AsyncSession) -> None:
    summary = await seed_sourcing_demo(db_session, count=4)
    assert summary["products_created"] == 4
    assert summary["products_seeded"] == 4


async def test_large_set_decision_spread(db_session: AsyncSession) -> None:
    """Generated products produce a realistic mix of decisions (not all AVOID)."""
    await seed_sourcing_demo(db_session, count=60)
    actions: Counter[str] = Counter()
    for g in range(56):  # 60 - 4 curated
        asin = f"B0DEM{g + 10000:05d}"
        actions[await _decision_action(db_session, asin)] += 1
    assert len(actions) >= 3, f"expected a spread of actions, got {dict(actions)}"
