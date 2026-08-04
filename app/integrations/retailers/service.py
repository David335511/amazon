"""Retailer service — fetch product data and feed the sourcing methodology.

Design decisions:
- Combines the SerpApi client and the per-retailer providers.
- ``to_sourcing_data`` maps a normalized RetailerProduct into the flat data
  dict the sourcing rules consume (``lowest_supplier_price``,
  ``supplier_count``, ``amazon_price``, ``in_stock``, ...).
- ``evaluate`` runs the existing sourcing rules against that data so the
  retailer snapshot can be scored with the same methodology (v1.0.0) as
  database-backed evaluations — no DB required.
- No database writes: this is a lightweight, on-demand lookup layer.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, ClassVar

from app.core.logging import get_logger
from app.integrations.retailers.client import SerpApiClient
from app.integrations.retailers.config import RetailerConfig
from app.integrations.retailers.models import (
    RetailerLookupRequest,
    RetailerProduct,
    RetailerProvider,
)
from app.integrations.retailers.providers import HomeDepotProvider, WalmartProvider
from app.profit.config import DEFAULT_PROFIT_CONFIG
from app.profit.engine import ProfitEngine
from app.profit.models import ProfitInput
from app.sourcing.models import (
    OpportunityScore,
    RuleResult,
    SourcingConfig,
)

logger = get_logger(__name__)


class RetailerService:
    """Business logic for retailer product lookups and sourcing scoring."""

    _PARSERS: ClassVar[dict[RetailerProvider, Callable[[dict[str, Any], str], RetailerProduct]]] = {
        RetailerProvider.WALMART: WalmartProvider.parse,
        RetailerProvider.HOME_DEPOT: HomeDepotProvider.parse,
    }

    def __init__(self, client: SerpApiClient) -> None:
        self._client = client

    # ── Lookup ─────────────────────────────────────────────

    async def fetch_product(
        self,
        request: RetailerLookupRequest,
        cache_ttl: int | None = None,
    ) -> RetailerProduct:
        """Fetch and normalize a product from a retailer.

        Args:
            request: Lookup parameters (provider + product id + locale).
            cache_ttl: Override the cache TTL in seconds.

        Returns:
            Normalized RetailerProduct.

        Raises:
            RetailerAuthenticationError: Missing/invalid API key.
            RetailerRequestError: Request failed or product not found.
        """
        parser = self._PARSERS[request.provider]
        raw = await self._client.fetch_product(
            provider=request.provider,
            product_id=request.product_id,
            country=request.country,
            delivery_zip=request.delivery_zip,
            store_id=request.store_id,
            cache_ttl=cache_ttl,
        )

        product = parser(raw, request.product_id)
        if product.title is None and product.price.current is None:
            logger.warning(
                "Empty product payload from %s for id=%s",
                request.provider.display_name,
                request.product_id,
            )
        return product

    # ── Mapping to sourcing data ───────────────────────────

    def to_sourcing_data(
        self,
        product: RetailerProduct,
        *,
        amazon_price: Decimal | None = None,
        fba_fulfillment_fee: Decimal = Decimal("0"),
        referral_fee_percent: Decimal | None = None,
    ) -> dict[str, object]:
        """Map a RetailerProduct into the sourcing engine's data dict.

        In a retail-arbitrage model the retailer is treated as the supplier:
        the retailer's price becomes the unit cost (``lowest_supplier_price``),
        and the optional ``amazon_price`` is the price you would sell at. When a
        sell price is supplied, profit metrics are computed through the shared
        ProfitEngine so the ROI and Profit sourcing rules score meaningfully.

        Args:
            product: Normalized retailer product.
            amazon_price: Optional expected selling price on Amazon. When
                omitted, it defaults to the retailer price (cost == sell, which
                yields zero profit — safe but not optimistic).
            fba_fulfillment_fee: Optional per-unit FBA fee to include.
            referral_fee_percent: Optional referral fee percentage (e.g. 15.00).

        Returns:
            A flat dict with the keys consumed by the sourcing rules.
        """
        cost = product.price.current or Decimal("0")
        sell = amazon_price if amazon_price is not None else cost

        # Profit metrics via the shared ProfitEngine.
        net_profit = Decimal("0")
        gross_profit = Decimal("0")
        roi_percentage = Decimal("0")
        margin_percentage = Decimal("0")
        if sell > 0 and cost > 0:
            try:
                result = ProfitEngine(config=DEFAULT_PROFIT_CONFIG).calculate(
                    ProfitInput(
                        amazon_price=sell,
                        supplier_price=cost,
                        quantity=1,
                        fba_fulfillment_fee=fba_fulfillment_fee,
                        referral_fee_percent=referral_fee_percent,
                    ),
                )
                net_profit = result.net_profit_per_unit
                gross_profit = result.gross_profit
                roi_percentage = result.roi_percentage
                margin_percentage = result.margin_percentage
            except Exception:
                logger.warning(
                    "Profit computation failed for %s id=%s",
                    product.provider.display_name,
                    product.product_id,
                )

        return {
            # Prices
            "amazon_price": sell,
            "buy_box_price": sell,
            "lowest_supplier_price": cost,
            "average_supplier_price": cost,
            "supplier_count": product.seller_count or 0,
            # Competition (retailer reports an offer/seller count, when present)
            "new_seller_count": product.seller_count or 0,
            "fba_seller_count": 0,
            "total_offer_count": product.seller_count or 0,
            # Demand: retailer product APIs do not report sales volume
            "estimated_monthly_sales": 0,
            "estimated_daily_sales": Decimal("0"),
            "sales_rank": None,
            # Fees: known only if supplied; ProfitEngine already accounted for them
            "referral_fee": referral_fee_percent or Decimal("0"),
            "fulfillment_fee": fba_fulfillment_fee,
            "storage_fee": Decimal("0"),
            "total_fees": fba_fulfillment_fee,
            # Inventory / availability
            "quantity_on_hand": 0,
            "quantity_reserved": 0,
            "quantity_inbound": 0,
            "quantity_available": 0,
            "days_of_stock": 0,
            # Price stability: single snapshot → assume stable
            "price_cv": Decimal("0"),
            "price_count": 1,
            "price_mean": cost,
            "price_stddev": Decimal("0"),
            "price_min": cost,
            "price_max": cost,
            # Buy Box: unknown → neutral 50%
            "buy_box_win_rate": Decimal("50"),
            # Profit metrics (computed via ProfitEngine when a sell price is set)
            "net_profit": net_profit,
            "gross_profit": gross_profit,
            "roi_percentage": roi_percentage,
            "margin_percentage": margin_percentage,
            # Data quality
            "total_data_points": 1,
            # Retailer context
            "source_provider": product.provider.value,
            "source_product_id": product.product_id,
            "in_stock": product.in_stock,
            "availability": product.availability,
        }

    # ── Scoring ────────────────────────────────────────────

    def score(
        self,
        data: dict[str, object],
        config: SourcingConfig | None = None,
    ) -> OpportunityScore:
        """Run the sourcing rules against a data dict and aggregate scores.

        Uses the same weighted-average methodology as the SourcingEngine
        (weighted_score = sum(score_i x weight_i) / sum(weight_i), x100).

        Args:
            data: The flat sourcing data dict (e.g. from ``to_sourcing_data``).
            config: Optional custom sourcing config; defaults to the standard one.

        Returns:
            OpportunityScore with rule results and viability.
        """
        from app.sourcing.rules import (
            BuyBoxStabilityRule,
            CompetitionRule,
            InventoryAvailabilityRule,
            MinimumProfitRule,
            MinimumRoiRule,
            MinimumSalesRule,
            PriceStabilityRule,
        )

        config = config or SourcingConfig()
        rules = [
            MinimumRoiRule(),
            MinimumProfitRule(),
            MinimumSalesRule(),
            CompetitionRule(),
            BuyBoxStabilityRule(),
            PriceStabilityRule(),
            InventoryAvailabilityRule(),
        ]
        rule_results: list[RuleResult] = [rule.evaluate(config, data) for rule in rules]

        total_weighted = Decimal("0")
        total_weight = Decimal("0")
        critical_failures = 0
        for result in rule_results:
            total_weighted += result.score * result.weight
            total_weight += result.weight
            if result.is_critical_failure:
                critical_failures += 1

        weighted = total_weighted / total_weight if total_weight > 0 else Decimal("0")
        total = (weighted * 100).quantize(Decimal("0.01"))

        is_viable = (
            critical_failures < config.critical_rule_fail_threshold
            and total >= config.minimum_opportunity_score
        )

        return OpportunityScore(
            total_score=total,
            weighted_score=weighted,
            rule_results=rule_results,
            critical_failures=critical_failures,
            is_viable=is_viable,
        )

    async def fetch_and_score(
        self,
        request: RetailerLookupRequest,
        *,
        amazon_price: Decimal | None = None,
        fba_fulfillment_fee: Decimal = Decimal("0"),
        referral_fee_percent: Decimal | None = None,
        config: SourcingConfig | None = None,
        cache_ttl: int | None = None,
    ) -> tuple[RetailerProduct, OpportunityScore]:
        """Fetch a retailer product and immediately score it.

        Convenience method combining ``fetch_product`` → ``to_sourcing_data``
        → ``score``. Returns the product and its opportunity score.

        Args:
            request: Lookup parameters.
            amazon_price: Optional expected Amazon selling price.
            fba_fulfillment_fee: Optional per-unit FBA fee.
            referral_fee_percent: Optional referral fee percentage.
            config: Optional custom sourcing config.
            cache_ttl: Override the cache TTL in seconds.

        Returns:
            Tuple of (product, opportunity_score).
        """
        product = await self.fetch_product(request, cache_ttl=cache_ttl)
        data = self.to_sourcing_data(
            product,
            amazon_price=amazon_price,
            fba_fulfillment_fee=fba_fulfillment_fee,
            referral_fee_percent=referral_fee_percent,
        )
        score = self.score(data, config=config)
        return product, score


def build_retailer_service() -> RetailerService:
    """Build a RetailerService using default config (no Redis cache)."""
    return RetailerService(client=SerpApiClient())


def parse_monitor_products(value: str) -> list[RetailerLookupRequest]:
    """Parse the ``SERPAPI_MONITOR_PRODUCTS`` env string into lookups.

    Format is comma-separated ``<provider>:<product_id>`` entries, e.g.
    ``"walmart:10291024, home_depot:203202930"``. Whitespace is tolerated and
    unknown providers are skipped (logged). Returns an empty list for an empty
    input.
    """
    lookups: list[RetailerLookupRequest] = []
    if not value:
        return lookups
    for entry in value.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        provider_raw, product_id = (part.strip() for part in entry.split(":", 1))
        try:
            provider = RetailerProvider(provider_raw.lower())
        except ValueError:
            logger.warning(
                "Ignoring unknown retailer provider %r in monitor list",
                provider_raw,
            )
            continue
        if product_id:
            lookups.append(RetailerLookupRequest(provider=provider, product_id=product_id))
    return lookups


# Re-export for convenient imports
__all__ = [
    "RetailerConfig",
    "RetailerLookupRequest",
    "RetailerProduct",
    "RetailerProvider",
    "RetailerService",
    "build_retailer_service",
    "parse_monitor_products",
]
